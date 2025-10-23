#include "server/rest_impl.hpp"

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
        const std::string id = subscriptions->enqueue(request, prefer_reuse_ready);
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
            return errorResponse("subscriptions: queue_full", 429);
        }
        return errorResponse(std::string("subscriptions: ") + msg, 500);
    }
}

  HttpResponse RestServer::Impl::handleSubscriptionGet(const HttpRequest& req, const std::string& id) {
    if (!subscriptions) {
        return errorResponse("subscription manager unavailable", 503);
    }
    auto state = subscriptions->get(id);
    if (!state) {
        return errorResponse("subscription not found", 404);
    }
    // ETag support (weak): derive from timestamps and current phase
    auto etag_hex = [&](){
        uint64_t acc = 0;
        acc ^= static_cast<uint64_t>(state->ts_pending.load());
        acc ^= static_cast<uint64_t>(state->ts_preparing.load());
        acc ^= static_cast<uint64_t>(state->ts_opening.load());
        acc ^= static_cast<uint64_t>(state->ts_loading.load());
        acc ^= static_cast<uint64_t>(state->ts_starting.load());
        acc ^= static_cast<uint64_t>(state->ts_ready.load());
        acc ^= static_cast<uint64_t>(state->ts_failed.load());
        acc ^= static_cast<uint64_t>(state->ts_cancelled.load());
        acc ^= static_cast<uint64_t>(static_cast<int>(state->phase.load()));
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
    data["phase"] = toString(state->phase.load());
    data["stream_id"] = state->request.stream_id;
    data["profile_id"] = state->request.profile_id;
    data["source_uri"] = state->request.source_uri;
    if (state->request.model_id) {
        data["model_id"] = *state->request.model_id;
    }
    if (!state->pipeline_key.empty()) {
        data["pipeline_key"] = state->pipeline_key;
    }
    if (!state->whep_url.empty()) {
        data["whep_url"] = state->whep_url;
    }
    if (!state->reason.empty()) {
        data["reason"] = state->reason;
    }
    const auto created = std::chrono::duration_cast<std::chrono::milliseconds>(state->created_at.time_since_epoch()).count();
    data["created_at_ms"] = static_cast<Json::UInt64>(created);
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
    if (sessions_repo) {
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
    if (!subscriptions->cancel(id)) {
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
    if (!subscriptions) return;
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
