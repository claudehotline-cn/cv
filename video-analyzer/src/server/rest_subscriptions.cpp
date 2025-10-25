#include "server/rest_impl.hpp"
#include "server/sse_metrics.hpp"

namespace va::server {

HttpResponse RestServer::Impl::handleSubscriptionCreate(const HttpRequest& req) {
    if (!subscriptions) {
        return errorResponse("subscription manager unavailable", 503);
    }
    try {
        const Json::Value body = parseJson(req.body);
        if (!body.isObject()) {
            return errorResponse("Invalid JSON: object required", 400);
        }
        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt || stream_opt->empty()) {
            return errorResponse("Missing required field: stream_id", 400);
        }
        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt || profile_opt->empty()) {
            return errorResponse("Missing required field: profile", 400);
        }
        auto uri_opt = getStringField(body, {"source_uri", "uri", "url"});
        if (!uri_opt || uri_opt->empty()) {
            return errorResponse("Missing required field: source_uri", 400);
        }
        SubscriptionRequest request;
        request.stream_id = *stream_opt;
        request.profile_id = *profile_opt;
        request.source_uri = *uri_opt;
        // Extract requester key for quotas
        const auto& quotas = app.appConfig().quotas;
        std::string header_name = quotas.header_key.empty()? std::string("X-API-Key") : quotas.header_key;
        std::string header_lc = toLower(header_name);
        for (const auto& h : req.headers) {
            if (toLower(h.first) == header_lc) { request.requester_key = h.second; break; }
        }
        if (body.isMember("model_id") && body["model_id"].isString()) {
            auto v = body["model_id"].asString();
            if (!v.empty()) request.model_id = v;
        }
        subscriptions->setWhepBase(app.appConfig().sfu_whep_base);
        bool prefer_reuse_ready = false;
        // 简易解析：query 中包含 use_existing=1 或头部 X-Subscription-Use-Existing: 1
        try {
            if (!req.query.empty()) {
                if (req.query.find("use_existing=1") != std::string::npos || req.query.find("use_existing=true") != std::string::npos) {
                    prefer_reuse_ready = true;
                }
            }
            auto it = req.headers.find("X-Subscription-Use-Existing");
            if (it != req.headers.end()) {
                std::string v = toLower(it->second);
                if (v == "1" || v == "true" || v == "yes") prefer_reuse_ready = true;
            }
        } catch (...) { /* ignore */ }
        // ACL checks (schemes and profiles) + quotas/gray release
        if (quotas.enabled) {
            // Exempt keys bypass
            auto keyEq = [&](const std::string& a, const std::string& b){ return toLower(a) == toLower(b); };
            bool exempt = false; for (const auto& ek : quotas.exempt_keys) { if (keyEq(ek, request.requester_key.value_or(std::string()))) { exempt = true; break; } }
            // Per-key overrides
            int key_cc = quotas.def.concurrent; int key_rpm = quotas.def.rate_per_min;
            bool ov_observe_only = false; bool ov_has_enf = false; int ov_enf_percent = -1;
            for (const auto& ov : quotas.key_overrides) {
                if (keyEq(ov.key, request.requester_key.value_or(std::string()))) {
                    if (ov.concurrent > 0) key_cc = ov.concurrent;
                    if (ov.rate_per_min > 0) key_rpm = ov.rate_per_min;
                    if (ov.enforce_percent >= 0 && ov.enforce_percent <= 100) { ov_has_enf = true; ov_enf_percent = ov.enforce_percent; }
                    if (ov.observe_only) ov_observe_only = true;
                }
            }
            // Decide enforcement (global → per-key override)
            bool enforce = true;
            if (quotas.observe_only || ov_observe_only) enforce = false; else enforce = true;
            int eff_enf_percent = ov_has_enf ? ov_enf_percent : quotas.enforce_percent;
            if (enforce && eff_enf_percent < 100) {
                int dice = std::rand() % 100; enforce = (dice < eff_enf_percent);
            }
            auto record_would = [&](const char* reason){
                if (enforce) return false; // if enforce==true, caller应立即 return
                if (std::strcmp(reason, "global_concurrent")==0) quota_would_drop_global_concurrent_.fetch_add(1, std::memory_order_relaxed);
                else if (std::strcmp(reason, "key_concurrent")==0) quota_would_drop_key_concurrent_.fetch_add(1, std::memory_order_relaxed);
                else if (std::strcmp(reason, "key_rate")==0) quota_would_drop_key_rate_.fetch_add(1, std::memory_order_relaxed);
                else if (std::strcmp(reason, "acl_scheme")==0) quota_would_drop_acl_scheme_.fetch_add(1, std::memory_order_relaxed);
                else if (std::strcmp(reason, "acl_profile")==0) quota_would_drop_acl_profile_.fetch_add(1, std::memory_order_relaxed);
                return true; // observed-only path: 允许继续
            };
            if (!exempt) {
            // scheme from source_uri
            auto src = request.source_uri;
            std::string sch; {
                auto p = src.find(":"); if (p != std::string::npos) sch = toLower(src.substr(0, p));
            }
            if (!quotas.acl.allowed_schemes.empty()) {
                bool ok = false;
                for (const auto& s : quotas.acl.allowed_schemes) { if (toLower(s) == sch) { ok = true; break; } }
                if (!ok) {
                    if (enforce) { quota_drop_acl_scheme_.fetch_add(1, std::memory_order_relaxed); HttpResponse resp = errorResponse("acl: scheme not allowed", 403); resp.headers["X-Quota-Reason"] = "acl_scheme"; std::string allowed; for (size_t i=0;i<quotas.acl.allowed_schemes.size();++i){ allowed += quotas.acl.allowed_schemes[i]; if (i+1<quotas.acl.allowed_schemes.size()) allowed += ','; } resp.headers["X-Quota-Advice"] = std::string("use one of schemes: ")+allowed; return resp; }
                    else { record_would("acl_scheme"); }
                }
            }
            if (!quotas.acl.allowed_profiles.empty()) {
                bool okp = false;
                for (const auto& p : quotas.acl.allowed_profiles) { if (p == request.profile_id) { okp = true; break; } }
                if (!okp) {
                    if (enforce) { quota_drop_acl_profile_.fetch_add(1, std::memory_order_relaxed); HttpResponse resp = errorResponse("acl: profile not allowed", 403); resp.headers["X-Quota-Reason"] = "acl_profile"; std::string allowed; for (size_t i=0;i<quotas.acl.allowed_profiles.size();++i){ allowed += quotas.acl.allowed_profiles[i]; if (i+1<quotas.acl.allowed_profiles.size()) allowed += ','; } resp.headers["X-Quota-Advice"] = std::string("use one of profiles: ")+allowed; return resp; }
                    else { record_would("acl_profile"); }
                }
            }
            // Concurrency quotas
            if (quotas.global.concurrent > 0) {
                auto ms = subscriptions->metricsSnapshot();
                if (static_cast<int>(ms.in_progress) >= quotas.global.concurrent) {
                    if (enforce) {
                        quota_drop_global_concurrent_.fetch_add(1, std::memory_order_relaxed);
                        HttpResponse resp = errorResponse("quota: global concurrent limit", 429);
                        std::string ra = "1";
                        try {
                            size_t qlen = subscriptions->metricsSnapshot().queue_length;
                            int s_open = subscriptions->openRtspSlots(); if (s_open <= 0) s_open = subscriptions->rtspSlots();
                            int s_load = subscriptions->modelSlots(); if (s_load <= 0) s_load = 1;
                            int s_start= subscriptions->startPipelineSlots(); if (s_start <= 0) s_start = 1;
                            int slots = std::max(1, std::min({s_open>0?s_open:1, s_load, s_start}));
                            int est = 1;
                            if (qlen > 0) { double wait = static_cast<double>(qlen) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
                            if (est < 1) est = 1; if (est > 60) est = 60; ra = std::to_string(est);
                        } catch (...) {}
                        resp.headers["Retry-After"] = ra;
                        resp.headers["X-Quota-Reason"] = "global_concurrent";
                        resp.headers["X-Quota-Advice"] = "reduce concurrency or retry later";
                        return resp;
                    } else { record_would("global_concurrent"); }
                }
            }
            const std::string key = request.requester_key.value_or(std::string());
            if (key_cc > 0) {
                int cur = subscriptions->countInProgressByKey(key);
                if (cur >= key_cc) {
                    if (enforce) {
                        quota_drop_key_concurrent_.fetch_add(1, std::memory_order_relaxed);
                        HttpResponse resp = errorResponse("quota: key concurrent limit", 429);
                        std::string ra = "1";
                        try {
                            size_t qlen = subscriptions->metricsSnapshot().queue_length;
                            int s_open = subscriptions->openRtspSlots(); if (s_open <= 0) s_open = subscriptions->rtspSlots();
                            int s_load = subscriptions->modelSlots(); if (s_load <= 0) s_load = 1;
                            int s_start= subscriptions->startPipelineSlots(); if (s_start <= 0) s_start = 1;
                            int slots = std::max(1, std::min({s_open>0?s_open:1, s_load, s_start}));
                            int est = 1;
                            if (qlen > 0) { double wait = static_cast<double>(qlen) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
                            if (est < 1) est = 1; if (est > 60) est = 60; ra = std::to_string(est);
                        } catch (...) {}
                        resp.headers["Retry-After"] = ra;
                        resp.headers["X-Quota-Reason"] = "key_concurrent";
                        resp.headers["X-Quota-Advice"] = "reduce concurrent requests for this key";
                        return resp;
                    } else { record_would("key_concurrent"); }
                }
            }
            if (key_rpm > 0) {
                auto now = static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                const std::uint64_t cutoff = now - 60000ULL;
                bool over = false;
                {
                    std::lock_guard<std::mutex> lk(quota_mu_);
                    auto& dq = quota_hits_by_key_ms_[key];
                    while (!dq.empty() && dq.front() < cutoff) dq.pop_front();
                    if (static_cast<int>(dq.size()) >= key_rpm) {
                        over = true;
                    } else {
                        dq.push_back(now);
                    }
                }
                if (over) {
                if (enforce) {
                    quota_drop_key_rate_.fetch_add(1, std::memory_order_relaxed);
                    HttpResponse resp = errorResponse("quota: key rate_per_min limit", 429);
                    std::string ra = "60";
                    try {
                        size_t qlen = subscriptions->metricsSnapshot().queue_length;
                        int s_open = subscriptions->openRtspSlots(); if (s_open <= 0) s_open = subscriptions->rtspSlots();
                        int s_load = subscriptions->modelSlots(); if (s_load <= 0) s_load = 1;
                        int s_start= subscriptions->startPipelineSlots(); if (s_start <= 0) s_start = 1;
                        int slots = std::max(1, std::min({s_open>0?s_open:1, s_load, s_start}));
                        int est = 60;
                        if (qlen > 0) { double wait = static_cast<double>(qlen) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
                        if (est < 1) est = 1; if (est > 60) est = 60; ra = std::to_string(est);
                    } catch (...) {}
                    resp.headers["Retry-After"] = ra;
                    resp.headers["X-Quota-Reason"] = "key_rate";
                    resp.headers["X-Quota-Advice"] = "wait and retry or request higher rate_per_min for your key";
                    return resp;
                }
                    else { record_would("key_rate"); }
                }
            }
            } // not exempt
        }
        std::string id;
        if (lro_enabled_ && lro_runner_) {
            const std::string base_key = request.stream_id + ":" + request.profile_id;
            id = lro_runner_->create(req.body.empty()? std::string("{}") : req.body, base_key, prefer_reuse_ready);
            if (id.empty()) {
                return errorResponse("LRO create failed", 500);
            }
        } else {
            id = subscriptions->enqueue(request, prefer_reuse_ready);
        }
        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        data["id"] = id;
        data["status"] = "accepted";
        data["phase"] = toString(SubscriptionPhase::Pending);
        data["stream_id"] = request.stream_id;
        data["profile_id"] = request.profile_id;
        payload["data"] = data;
        // Record session start (best-effort)
        if (sessions_repo) {
            std::string err; std::int64_t sid = 0;
            const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
            (void)sessions_repo->start(request.stream_id, request.profile_id, request.model_id.value_or(std::string()), request.source_uri, now_ms, &sid, &err);
        }
        // 202 + Location header for polling follow-up
        HttpResponse resp;
        resp.status_code = 202;
        Json::StreamWriterBuilder b; resp.body = Json::writeString(b, payload);
        resp.headers["Location"] = std::string("/api/subscriptions/") + id;
        resp.headers["Access-Control-Expose-Headers"] = "Location";
        return resp;
    } catch (const std::exception& ex) {
        const std::string msg = ex.what();
        if (msg.find("queue_full") != std::string::npos) {
            HttpResponse resp = errorResponse("subscriptions: queue_full", 429);
            // 动态补齐 Retry-After
            std::string ra = "1";
            try {
                size_t qlen = subscriptions->metricsSnapshot().queue_length;
                int s_open = subscriptions->openRtspSlots(); if (s_open <= 0) s_open = subscriptions->rtspSlots();
                int s_load = subscriptions->modelSlots(); if (s_load <= 0) s_load = 1;
                int s_start= subscriptions->startPipelineSlots(); if (s_start <= 0) s_start = 1;
                int slots = std::max(1, std::min({s_open>0?s_open:1, s_load, s_start}));
                int est = 1;
                if (qlen > 0) { double wait = static_cast<double>(qlen) / static_cast<double>(slots); est = std::max(est, static_cast<int>(std::ceil(wait))); }
                if (est < 1) est = 1; if (est > 60) est = 60; ra = std::to_string(est);
            } catch (...) {}
            resp.headers["Retry-After"] = ra;
            return resp;
        }
        return errorResponse(std::string("subscriptions: ") + msg, 500);
    }
}

  HttpResponse RestServer::Impl::handleSubscriptionGet(const HttpRequest& req, const std::string& id) {
    // Prefer LRO snapshot when enabled; fallback to legacy manager
    lro::Operation op;
    if (lro_enabled_ && lro_runner_) {
        op = lro_runner_->get(id);
        if (op.id.empty() && !subscriptions) {
            return errorResponse("subscription not found", 404);
        }
    }
    std::shared_ptr<SubscriptionState> state;
    if (subscriptions && op.id.empty()) {
        state = subscriptions->get(id);
        if (!state) {
            return errorResponse("subscription not found", 404);
        }
    }
    // ETag support (weak): derive from timestamps and current phase
    auto etag_hex = [&](){
        uint64_t acc = 0;
        if (!op.id.empty()) {
            acc ^= op.timeline.ts_pending;
            acc ^= op.timeline.ts_preparing;
            acc ^= op.timeline.ts_opening;
            acc ^= op.timeline.ts_loading;
            acc ^= op.timeline.ts_starting;
            acc ^= op.timeline.ts_ready;
            acc ^= op.timeline.ts_failed;
            acc ^= op.timeline.ts_cancelled;
        } else {
            acc ^= static_cast<uint64_t>(state->ts_pending.load());
            acc ^= static_cast<uint64_t>(state->ts_preparing.load());
            acc ^= static_cast<uint64_t>(state->ts_opening.load());
            acc ^= static_cast<uint64_t>(state->ts_loading.load());
            acc ^= static_cast<uint64_t>(state->ts_starting.load());
            acc ^= static_cast<uint64_t>(state->ts_ready.load());
            acc ^= static_cast<uint64_t>(state->ts_failed.load());
            acc ^= static_cast<uint64_t>(state->ts_cancelled.load());
            acc ^= static_cast<uint64_t>(static_cast<int>(state->phase.load()));
        }
        std::ostringstream os; os << 'W' << '/' << std::hex << acc; return os.str();
    }();
    // If-None-Match handling
    std::string inm;
    try { for (const auto& kv : req.headers) { if (toLower(kv.first) == "if-none-match") { inm = kv.second; break; } } } catch (...) {}
    if (!inm.empty() && inm == etag_hex) {
        HttpResponse notmod; notmod.status_code = 304; notmod.headers["ETag"] = etag_hex; return notmod;
    }
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    data["id"] = id;
    data["phase"] = (!op.id.empty() ? Json::Value(op.status.phase) : Json::Value(toString(state->phase.load())));
    std::string stream_id, profile_id, source_uri;
    if (!op.id.empty()) {
        try {
            Json::Value sx = parseJson(op.spec_json);
            if (sx.isObject()) {
                if (sx.isMember("stream_id") && sx["stream_id"].isString()) stream_id = sx["stream_id"].asString();
                if (sx.isMember("stream") && stream_id.empty() && sx["stream"].isString()) stream_id = sx["stream"].asString();
                if (sx.isMember("profile") && sx["profile"].isString()) profile_id = sx["profile"].asString();
                if (sx.isMember("profile_id") && profile_id.empty() && sx["profile_id"].isString()) profile_id = sx["profile_id"].asString();
                if (sx.isMember("source_uri") && sx["source_uri"].isString()) source_uri = sx["source_uri"].asString();
                if (sx.isMember("uri") && source_uri.empty() && sx["uri"].isString()) source_uri = sx["uri"].asString();
                if (sx.isMember("url") && source_uri.empty() && sx["url"].isString()) source_uri = sx["url"].asString();
            }
        } catch (...) {}
    } else {
        stream_id = state->request.stream_id; profile_id = state->request.profile_id; source_uri = state->request.source_uri;
    }
    if (!stream_id.empty()) data["stream_id"] = stream_id;
    if (!profile_id.empty()) data["profile_id"] = profile_id;
    if (!source_uri.empty()) data["source_uri"] = source_uri;
    if (!op.id.empty()) {
        try { Json::Value sx = parseJson(op.spec_json); if (sx.isMember("model_id") && sx["model_id"].isString()) data["model_id"] = sx["model_id"].asString(); } catch (...) {}
        // pipeline_key: for Application path we used pipeline key as id
        data["pipeline_key"] = id;
        if (!op.status.reason.empty()) data["reason"] = op.status.reason;
    } else {
        if (state->request.model_id) data["model_id"] = *state->request.model_id;
        if (!state->pipeline_key.empty()) data["pipeline_key"] = state->pipeline_key;
        if (!state->whep_url.empty()) data["whep_url"] = state->whep_url;
        if (!state->reason.empty()) data["reason"] = state->reason;
    }
    if (state) {
        const auto created = std::chrono::duration_cast<std::chrono::milliseconds>(state->created_at.time_since_epoch()).count();
        data["created_at_ms"] = static_cast<Json::UInt64>(created);
    } else if (!op.id.empty() && op.timeline.ts_pending > 0) {
        data["created_at_ms"] = static_cast<Json::UInt64>(op.timeline.ts_pending);
    }
    // include=timeline 支持
    auto q = parseQueryKV(req.query);
    auto itInc = q.find("include");
    if (itInc != q.end()) {
        std::string inc = toLower(itInc->second);
        if (inc.find("timeline") != std::string::npos) {
            Json::Value tl(Json::objectValue);
            auto put_ts = [&](const char* k, std::uint64_t v) { if (v>0) tl[k] = static_cast<Json::UInt64>(v); };
            put_ts("pending", state->ts_pending.load());
            put_ts("preparing", state->ts_preparing.load());
            put_ts("opening_rtsp", state->ts_opening.load());
            put_ts("loading_model", state->ts_loading.load());
            put_ts("starting_pipeline", state->ts_starting.load());
            put_ts("ready", state->ts_ready.load());
            put_ts("failed", state->ts_failed.load());
            put_ts("cancelled", state->ts_cancelled.load());
            data["timeline"] = tl;
        }
    }
    // Persist completion if terminal (best-effort, once)
    if (sessions_repo && state) {
        auto ph = state->phase.load();
        if (ph == SubscriptionPhase::Ready || ph == SubscriptionPhase::Failed || ph == SubscriptionPhase::Cancelled) {
            bool expected = false;
            if (state->db_recorded.compare_exchange_strong(expected, true)) {
                std::string err;
                const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                const char* status = (ph == SubscriptionPhase::Ready) ? "Ready" : (ph == SubscriptionPhase::Failed ? "Failed" : "Cancelled");
                const std::string errmsg = state->reason;
                (void)sessions_repo->completeLatest(state->request.stream_id, state->request.profile_id, status, errmsg, now_ms, &err);
            }
        }
    }
    payload["data"] = data;
    HttpResponse resp = jsonResponse(payload, 200);
    resp.headers["ETag"] = etag_hex;
    resp.headers["Access-Control-Expose-Headers"] = "ETag";
    return resp;
}

HttpResponse RestServer::Impl::handleSubscriptionDelete(const HttpRequest& /*req*/, const std::string& id) {
    if (!subscriptions) {
        return errorResponse("subscription manager unavailable", 503);
    }
    bool ok = false;
    if (lro_enabled_ && lro_runner_) {
        ok = lro_runner_->cancel(id);
    } else {
        ok = subscriptions->cancel(id);
    }
    if (!ok) {
        return errorResponse("subscription not found", 404);
    }
    // Persist cancellation for session (best-effort)
    if (sessions_repo) {
        auto st = subscriptions->get(id);
        if (st) {
            bool expected = false;
            if (st->db_recorded.compare_exchange_strong(expected, true)) {
                std::string err;
                const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                (void)sessions_repo->completeLatest(st->request.stream_id, st->request.profile_id, "Cancelled", std::string(), now_ms, &err);
            }
        }
    }
    Json::Value payload = successPayload();
    payload["data"]["id"] = id;
    payload["data"]["status"] = "cancelled";
    return jsonResponse(payload, 202);
}

HttpResponse RestServer::Impl::handleSubscribe(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing stream identifier";
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing profile";
            return errorResponse("Missing required field: profile", 400);
        }

        auto uri_opt = getStringField(body, {"source_uri", "url"});
        if (!uri_opt) {
            VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing source URI";
            return errorResponse("Missing required field: source_uri", 400);
        }

        const std::string stream_id = *stream_opt;
        const std::string profile = *profile_opt;
        const std::string uri = *uri_opt;

        VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe request stream=" << stream_id
                      << " profile=" << profile
                      << " uri=" << uri;
        std::optional<std::string> model_override;
        if (body.isMember("model_id") && body["model_id"].isString()) {
            model_override = body["model_id"].asString();
        }

        VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe -> building pipeline...";
        auto result = app.subscribeStream(stream_id, profile, uri, model_override);
        if (!result) {
            // Record Failed session attempt (best-effort)
            if (sessions_repo) {
                std::string err; std::int64_t id = 0;
                const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                (void)sessions_repo->start(stream_id, profile, model_override.value_or(std::string()), uri, now_ms, &id, &err);
                (void)sessions_repo->completeLatest(stream_id, profile, "Failed", app.lastError().empty()? std::string("subscribe failed") : app.lastError(), now_ms, &err);
            }
            return errorResponse(app.lastError(), 400);
        }
        VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe -> pipeline created key=" << *result;

        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        data["subscription_id"] = *result;
        data["pipeline_key"] = *result;
        data["stream_id"] = stream_id;
        data["profile"] = profile;
        if (model_override) {
            data["model_id"] = *model_override;
        }
        payload["data"] = data;
        // Sessions: start record
        if (sessions_repo) {
            std::string err; std::int64_t id = 0;
            const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
            (void)sessions_repo->start(stream_id, profile, model_override.value_or(std::string()), uri, now_ms, &id, &err);
        }
        // DB: event + log
        emitEvent("info", "subscribe", profile, "rest", stream_id, std::string("uri=") + uri);
        emitLog("info", profile, "rest", stream_id, std::string("subscribe accepted: ") + *result);
        return jsonResponse(payload, 201);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleUnsubscribe(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            return errorResponse("Missing required field: profile", 400);
        }

        const bool success = app.unsubscribeStream(*stream_opt, *profile_opt);
        if (!success) {
            return errorResponse(app.lastError().empty() ? "unsubscribe failed" : app.lastError(), 400);
        }

        Json::Value payload = successPayload();
        // Sessions: complete latest
        if (sessions_repo) {
            std::string err; const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
            (void)sessions_repo->completeLatest(*stream_opt, *profile_opt, "Stopped", std::string(), now_ms, &err);
        }
        emitEvent("info", "unsubscribe", *profile_opt, "rest", *stream_opt, "ok");
        emitLog("info", *profile_opt, "rest", *stream_opt, "unsubscribe accepted");
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleSourceSwitch(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            return errorResponse("Missing required field: profile", 400);
        }

        auto uri_opt = getStringField(body, {"source_uri", "url"});
        if (!uri_opt) {
            return errorResponse("Missing required field: source_uri", 400);
        }

        if (!app.switchSource(*stream_opt, *profile_opt, *uri_opt)) {
            return errorResponse(app.lastError().empty() ? "switch source failed" : app.lastError(), 400);
        }

        Json::Value payload = successPayload();
        emitEvent("info", "switch_source", *profile_opt, "rest", *stream_opt, std::string("uri=") + *uri_opt);
        emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_source -> ") + *uri_opt);
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleModelSwitch(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            return errorResponse("Missing required field: profile", 400);
        }

        auto model_opt = getStringField(body, {"model_id"});
        if (!model_opt) {
            return errorResponse("Missing required field: model_id", 400);
        }

        if (!app.switchModel(*stream_opt, *profile_opt, *model_opt)) {
            return errorResponse(app.lastError().empty() ? "switch model failed" : app.lastError(), 400);
        }

        Json::Value payload = successPayload();
        emitEvent("info", "switch_model", *profile_opt, "rest", *stream_opt, std::string("model=") + *model_opt);
        emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_model -> ") + *model_opt);
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleTaskSwitch(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            return errorResponse("Missing required field: profile", 400);
        }

        auto task_opt = getStringField(body, {"task", "task_id"});
        if (!task_opt) {
            return errorResponse("Missing required field: task", 400);
        }

        if (!app.switchTask(*stream_opt, *profile_opt, *task_opt)) {
            return errorResponse(app.lastError().empty() ? "switch task failed" : app.lastError(), 400);
        }

        Json::Value payload = successPayload();
        emitEvent("info", "switch_task", *profile_opt, "rest", *stream_opt, std::string("task=") + *task_opt);
        emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_task -> ") + *task_opt);
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleParamsUpdate(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);

        auto stream_opt = getStringField(body, {"stream_id", "stream"});
        if (!stream_opt) {
            return errorResponse("Missing required field: stream_id", 400);
        }

        auto profile_opt = getStringField(body, {"profile", "profile_id"});
        if (!profile_opt) {
            return errorResponse("Missing required field: profile", 400);
        }

        auto params = buildParamsFromJson(body);
        if (!app.updateParams(*stream_opt, *profile_opt, params)) {
            return errorResponse(app.lastError().empty() ? "update params failed" : app.lastError(), 400);
        }

        Json::Value payload = successPayload();
        payload["conf"] = params.confidence_threshold;
        payload["iou"] = params.iou_threshold;
        emitEvent("info", "update_params", *profile_opt, "rest", *stream_opt, "params updated");
        emitLog("info", *profile_opt, "rest", *stream_opt, "params updated");
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleSetEngine(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);
        // Log incoming request summary (do not dump entire body to avoid noise)
        try {
            std::string t = body.isMember("type") && body["type"].isString() ? body["type"].asString() : "";
            std::string p = body.isMember("provider") && body["provider"].isString() ? body["provider"].asString() : "";
            int d = body.isMember("device") && body["device"].isInt() ? body["device"].asInt() : -1;
            std::string opt_keys;
            if (body.isMember("options") && body["options"].isObject()) {
                const auto& opts = body["options"]; auto names = opts.getMemberNames();
                for (size_t i=0;i<names.size();++i) { opt_keys += names[i]; if (i+1<names.size()) opt_keys += ","; }
            }
            VA_LOG_C(::va::core::LogLevel::Info, "rest")
                << "engine.set called type='" << t << "' provider='" << p << "' device=" << d
                << " option_keys=[" << opt_keys << "] (merge update)";
        } catch (...) { /* best-effort logging */ }
        // Merge semantics: start from current engine, override only provided fields
        auto current = app.currentEngine();
        va::core::EngineDescriptor desc = current;

        if (body.isMember("type") && body["type"].isString()) {
            desc.name = body["type"].asString();
            // If provider not provided, keep existing; do NOT auto-sync to type to avoid unexpected changes
        }
        if (body.isMember("provider") && body["provider"].isString()) {
            desc.provider = body["provider"].asString();
        }
        if (body.isMember("device") && body["device"].isInt()) {
            desc.device_index = body["device"].asInt();
        }
        if (body.isMember("options") && body["options"].isObject()) {
            const auto& opts = body["options"];
            for (const auto& k : opts.getMemberNames()) {
                // Overwrite/insert provided options; leave others untouched
                desc.options[k] = opts[k].asString();
            }
        }

        if (!app.setEngine(desc)) {
            return errorResponse(app.lastError().empty() ? "set engine failed" : app.lastError(), 400);
        }
        // Echo final keys
        try {
            std::string keys; for (const auto& kv : desc.options) { keys += kv.first; keys += ","; }
            if (!keys.empty()) keys.pop_back();
            VA_LOG_C(::va::core::LogLevel::Info, "rest") << "engine.set applied option_keys=[" << keys << "]";
        } catch (...) {}

        Json::Value payload = successPayload();
        payload["type"] = desc.name;
        payload["provider"] = desc.provider;
        payload["device"] = desc.device_index;
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

void RestServer::Impl::streamSubscriptionSSE(int fd, const HttpRequest& req, const std::string& id) {
    if (lro_enabled_ && lro_runner_) {
        struct Guard { ~Guard(){ va::server::g_sse_subscriptions_active.fetch_sub(1, std::memory_order_relaxed); } } guard;
        va::server::g_sse_subscriptions_active.fetch_add(1, std::memory_order_relaxed);
        try { auto it=req.headers.find("Last-Event-ID"); if (it!=req.headers.end()) va::server::g_sse_reconnects_total.fetch_add(1ULL, std::memory_order_relaxed); } catch (...) {}
        sseWriteHeaders(fd);
        auto last = std::string();
        bool first = true;
        const int interval_ms = 200;
        const int keepalive_ms = 10000;
        auto last_keepalive = std::chrono::steady_clock::now();
        std::uint64_t ev_id = 1;
        auto hit = req.headers.find("Last-Event-ID"); if (hit != req.headers.end()) { try { ev_id = static_cast<std::uint64_t>(std::stoull(hit->second) + 1ULL); } catch (...) {} }
        while (true) {
            auto op = lro_runner_->get(id);
            if (op.id.empty()) { Json::Value e; e["error"] = "not_found"; sseEvent(fd, "error", e); return; }
            if (first || op.status.phase != last) {
                Json::Value data(Json::objectValue);
                data["id"] = id;
                data["phase"] = op.status.phase;
                if (!op.status.reason.empty()) data["reason"] = op.status.reason;
                data["pipeline_key"] = id;
                sseEventWithId(fd, "phase", data, ev_id++, 2500);
                last = op.status.phase; first = false;
                if (last == "ready" || last == "failed" || last == "cancelled") break;
            }
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_keepalive).count() >= keepalive_ms) { sseKeepAlive(fd); last_keepalive = now; }
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
        }
        return;
    }
    if (!subscriptions) return;
    // SSE metrics: active connections and reconnects
    struct Guard { ~Guard(){ va::server::g_sse_subscriptions_active.fetch_sub(1, std::memory_order_relaxed); } } guard;
    va::server::g_sse_subscriptions_active.fetch_add(1, std::memory_order_relaxed);
    try { auto it=req.headers.find("Last-Event-ID"); if (it!=req.headers.end()) va::server::g_sse_reconnects_total.fetch_add(1ULL, std::memory_order_relaxed); } catch (...) {}
    sseWriteHeaders(fd);
    auto state = subscriptions->get(id);
    if (!state) { Json::Value e; e["error"] = "not_found"; sseEvent(fd, "error", e); return; }
    auto last = SubscriptionPhase::Pending;
    bool first = true;
    const int interval_ms = 200;
    const int keepalive_ms = 10000;
    auto last_keepalive = std::chrono::steady_clock::now();
    // Last-Event-ID 支持：从请求头恢复事件序号
    std::uint64_t ev_id = 1;
    auto hit = req.headers.find("Last-Event-ID");
    if (hit != req.headers.end()) {
        try { ev_id = static_cast<std::uint64_t>(std::stoull(hit->second) + 1ULL); } catch (...) {}
    }
    while (true) {
        auto st = subscriptions->get(id);
        if (!st) break;
        auto ph = st->phase.load();
        if (first || ph != last) {
            Json::Value data(Json::objectValue);
            data["id"] = id;
            data["phase"] = toString(ph);
            if (!st->reason.empty()) data["reason"] = st->reason;
            if (!st->pipeline_key.empty()) data["pipeline_key"] = st->pipeline_key;
            if (!st->whep_url.empty()) data["whep_url"] = st->whep_url;
            sseEventWithId(fd, "phase", data, ev_id++, 2500);
            // On terminal state, persist a session completion record once (best-effort)
            if ((ph == SubscriptionPhase::Ready || ph == SubscriptionPhase::Failed || ph == SubscriptionPhase::Cancelled) && sessions_repo) {
                bool expected = false;
                if (st->db_recorded.compare_exchange_strong(expected, true)) {
                    std::string err;
                    const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                    const char* status = (ph == SubscriptionPhase::Ready) ? "Ready" : (ph == SubscriptionPhase::Failed ? "Failed" : "Cancelled");
                    const std::string errmsg = st->reason;
                    (void)sessions_repo->completeLatest(st->request.stream_id, st->request.profile_id, status, errmsg, now_ms, &err);
                }
            }
            last = ph; first = false;
            if (ph == SubscriptionPhase::Ready || ph == SubscriptionPhase::Failed || ph == SubscriptionPhase::Cancelled) break;
        }
        // keepalive
        auto now = std::chrono::steady_clock::now();
        if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_keepalive).count() >= keepalive_ms) {
            sseKeepAlive(fd);
            last_keepalive = now;
        }
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
    }
}

} // namespace va::server
