#include "server/rest_impl.hpp"
#include "server/sse_metrics.hpp"

namespace va::server {

HttpResponse RestServer::Impl::handleSources(const HttpRequest& req) {
    // DB-only listing of sources; on failure, return error for frontend to显示
    if (!sources_repo) {
        return errorResponse("database disabled", 503);
    }
    // Parse pagination
    auto q = parseQueryKV(req.query);
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...) { return def; } };
    auto page = get_int("page", 1);
    auto page_size = get_int("page_size", 100);
    auto limit = get_int("limit", 0);

    std::vector<va::storage::SourceRow> rows; std::string err; std::int64_t total = 0;
    bool ok = false;
    if (limit > 0) {
        ok = sources_repo->listTopN(limit, &rows, &err);
        total = static_cast<std::int64_t>(rows.size());
    } else {
        ok = sources_repo->listPaged(page, page_size, &rows, &total, &err);
    }
    if (!ok) {
        return errorResponse(err.empty()? std::string("db query failed") : err, 503);
    }
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    Json::Value arr(Json::arrayValue);
    for (const auto& r : rows) {
        Json::Value node(Json::objectValue);
        node["id"] = r.id;
        node["name"] = r.id;
        node["uri"] = r.uri;
        node["status"] = r.status;
        node["fps"] = r.fps;
        if (!r.caps_json.empty()) {
            try {
                Json::CharReaderBuilder b; std::string errs; std::istringstream iss(r.caps_json); Json::Value caps; if (Json::parseFromStream(b, iss, &caps, &errs)) node["caps"] = caps; else node["caps_raw"] = r.caps_json;
            } catch (...) { node["caps_raw"] = r.caps_json; }
        }
        arr.append(node);
    }
    data["items"] = arr;
    if (limit <= 0) { data["total"] = static_cast<Json::UInt64>(total); data["page"] = page; data["page_size"] = page_size; }
    payload["data"] = data; return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleSourcesWatch(const HttpRequest& req) {
    // Long-poll style: if since==current rev, wait up to timeout_ms for change; else return immediately
    auto q = parseQueryKV(req.query);
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try{ return static_cast<uint64_t>(std::stoull(it->second)); }catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...) { return def; } };

    auto snapshot = [&]() {
        // Reuse aggregation
        struct Agg { std::string id; std::string uri; bool running{false}; double fps{0.0}; };
        std::unordered_map<std::string, Agg> by_id;
        for (const auto& info : app.pipelines()) {
            auto it = by_id.find(info.stream_id);
            if (it == by_id.end()) {
                Agg a; a.id = info.stream_id; a.uri = info.source_uri; a.running = info.running; a.fps = info.metrics.fps; by_id.emplace(info.stream_id, a);
            } else {
                it->second.running = it->second.running || info.running;
                if (info.metrics.fps > it->second.fps) it->second.fps = info.metrics.fps;
                if (it->second.uri.empty()) it->second.uri = info.source_uri;
            }
        }
        // compute fingerprint
        std::string concat;
        concat.reserve(by_id.size()*32);
        for (auto& kv : by_id) {
            concat += kv.second.id; concat += '|';
            concat += kv.second.running ? '1' : '0'; concat += '|';
            concat += std::to_string(static_cast<int>(kv.second.fps)); concat += ';';
        }
        uint64_t rev = std::hash<std::string>{}(concat);
        Json::Value items(Json::arrayValue);
        for (auto& kv : by_id) {
            const auto& a = kv.second;
            Json::Value node(Json::objectValue);
            node["id"] = a.id; node["name"] = a.id; node["uri"] = a.uri; node["status"] = a.running ? "Running" : "Stopped"; node["fps"] = a.fps; items.append(node);
        }
        return std::make_pair(rev, items);
    };

    const uint64_t since = get_uint64("since", 0);
    { /* avoid Windows min/max macros issues by not using std::max here */ }
    int tmp_timeout = get_int("timeout_ms", 12000); if (tmp_timeout < 100) tmp_timeout = 100; const int timeout_ms = tmp_timeout;
    int tmp_interval = get_int("interval_ms", 300); if (tmp_interval < 80) tmp_interval = 80; const int interval_ms = tmp_interval;

    auto snap = snapshot();
    if (since == 0 || since != snap.first) {
        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        data["rev"] = static_cast<Json::UInt64>(snap.first);
        data["items"] = snap.second;
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }
    // wait loop
    auto start = std::chrono::steady_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
        auto cur = snapshot();
        if (cur.first != since) {
            Json::Value payload = successPayload();
            Json::Value data(Json::objectValue);
            data["rev"] = static_cast<Json::UInt64>(cur.first);
            data["items"] = cur.second;
            payload["data"] = data;
            return jsonResponse(payload, 200);
        }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
        if (elapsed >= timeout_ms) {
            // keepalive payload with same rev, empty items to signal no-change
            Json::Value payload = successPayload();
            Json::Value data(Json::objectValue);
            data["rev"] = static_cast<Json::UInt64>(since);
            data["items"] = Json::arrayValue;
            payload["data"] = data;
            return jsonResponse(payload, 200);
        }
    }
}

void RestServer::Impl::streamSourcesSSE(int fd, const HttpRequest& req) {
    struct Guard { ~Guard(){ va::server::g_sse_sources_active.fetch_sub(1, std::memory_order_relaxed); } } guard;
    va::server::g_sse_sources_active.fetch_add(1, std::memory_order_relaxed);
    try { auto it=req.headers.find("Last-Event-ID"); if (it!=req.headers.end()) va::server::g_sse_reconnects_total.fetch_add(1ULL, std::memory_order_relaxed); } catch (...) {}
    sseWriteHeaders(fd);
    auto q = parseQueryKV(req.query);
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try{ return static_cast<uint64_t>(std::stoull(it->second)); }catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...) { return def; } };
    const int interval_ms = (std::max)(80, get_int("interval_ms", 300));
    const int keepalive_ms = (std::max)(1000, get_int("keepalive_ms", 15000));

    auto make_snapshot = [&]() {
        struct Agg { std::string id; std::string uri; bool running{false}; double fps{0.0}; };
        std::unordered_map<std::string, Agg> by_id;
        for (const auto& info : app.pipelines()) {
            auto it = by_id.find(info.stream_id);
            if (it == by_id.end()) {
                Agg a; a.id = info.stream_id; a.uri = info.source_uri; a.running = info.running; a.fps = info.metrics.fps; by_id.emplace(info.stream_id, a);
            } else {
                it->second.running = it->second.running || info.running;
                if (info.metrics.fps > it->second.fps) it->second.fps = info.metrics.fps;
                if (it->second.uri.empty()) it->second.uri = info.source_uri;
            }
        }
        // Merge VSM lightweight list
        if (auto snap = vsm_sources_snapshot(600); snap && snap->isArray()) {
            for (const auto& s : *snap) {
                std::string id = s.isMember("id")? s["id"].asString() : (s.isMember("attach_id")? s["attach_id"].asString() : "");
                if (id.empty()) continue; auto& a = by_id[id]; if (a.id.empty()) a.id = id; if (a.uri.empty() && s.isMember("uri")) a.uri = s["uri"].asString();
            }
        }
        Json::Value items(Json::arrayValue);
        for (auto& kv : by_id) {
            const auto& a = kv.second; Json::Value n(Json::objectValue);
            n["id"] = a.id; n["name"] = a.id; n["uri"] = a.uri; n["status"] = a.running?"Running":"Stopped"; n["fps"] = a.fps;
            items.append(n);
        }
        return items;
    };
    auto fingerprint = [&]() {
        std::string key; key.reserve(64);
        for (const auto& p : app.pipelines()) { key += p.stream_id; key += p.running? '1':'0'; key += ';'; }
        return std::hash<std::string>{}(key);
    };

    uint64_t last_rev = 0; uint64_t last_keep = 0;
    // Initial burst
    {
        Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(fingerprint()); data["items"] = make_snapshot();
        sseEvent(fd, "sources", data); last_rev = data["rev"].asUInt64();
    }
    auto start = std::chrono::steady_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
        auto rev = fingerprint();
        if (rev != last_rev) {
            Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev); data["items"] = make_snapshot(); sseEvent(fd, "sources", data); last_rev = rev; last_keep = 0; continue;
        }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
        if (elapsed - last_keep >= keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
    }
}

} // namespace va::server
