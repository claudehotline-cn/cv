#include "server/rest_impl.hpp"

namespace va::server {

// --- Sessions: list with pagination/time-window ---
HttpResponse RestServer::Impl::handleSessionsList(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string stream = q.count("stream_id") ? q["stream_id"] : std::string();
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
    const uint64_t from_ts = get_uint64("from_ts", 0);
    const uint64_t to_ts   = get_uint64("to_ts", 0);
    int page = get_int("page", 1);
    int page_size = get_int("page_size", 0);
    int limit = get_int("limit", 50);
    if (page_size <= 0) page_size = limit > 0 ? limit : 50;
    if (!sessions_repo) {
        return errorResponse("database disabled", 503);
    }
    std::vector<va::storage::SessionRow> rows; std::uint64_t total = 0; std::string err;
    if (!sessions_repo->listRangePaginated(stream, pipeline, from_ts, to_ts, page, page_size, &rows, &total, &err)) {
        return errorResponse(err.empty()? std::string("db query failed") : err, 503);
    }
    Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
    for (const auto& r : rows) {
        Json::Value s(Json::objectValue);
        s["id"] = static_cast<Json::UInt64>(r.id);
        s["stream_id"] = r.stream_id; s["pipeline"] = r.pipeline; if(!r.model_id.empty()) s["model_id"] = r.model_id; s["status"] = r.status; if(!r.error_msg.empty()) s["error_msg"] = r.error_msg;
        if (r.started_ms>0) s["started_at"] = static_cast<Json::UInt64>(r.started_ms);
        if (r.stopped_ms>0) s["stopped_at"] = static_cast<Json::UInt64>(r.stopped_ms);
        arr.append(s);
    }
    data["items"] = arr; data["total"] = static_cast<Json::UInt64>(total); payload["data"] = data; return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleSessionsWatch(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string stream = q.count("stream_id") ? q["stream_id"] : std::string();
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
    const uint64_t since = get_uint64("since", 0);
    int tmp_to = get_int("timeout_ms", 12000); if (tmp_to < 100) tmp_to = 100; const int timeout_ms = tmp_to;
    int tmp_iv = get_int("interval_ms", 300);  if (tmp_iv < 80)  tmp_iv = 80;  const int interval_ms = tmp_iv;
    int limit = 50; if (auto it=q.find("limit"); it!=q.end()) { try { limit = std::stoi(it->second); } catch(...) {} }
    auto fingerprint = [&]() { std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; if (!stream.empty() && p.stream_id != stream) continue; key += p.stream_id; key += ';'; } return std::hash<std::string>{}(key); };
    auto snapshot = [&]() { Json::Value items(Json::arrayValue); if (sessions_repo) { std::vector<va::storage::SessionRow> rows; std::string err; if (sessions_repo->listRecent(stream, pipeline, limit, &rows, &err)) { for (const auto& r : rows) { Json::Value s(Json::objectValue); s["id"] = static_cast<Json::UInt64>(r.id); s["stream_id"] = r.stream_id; s["pipeline"] = r.pipeline; if(!r.model_id.empty()) s["model_id"] = r.model_id; s["status"] = r.status; if(!r.error_msg.empty()) s["error_msg"] = r.error_msg; if (r.started_ms>0) s["started_at"] = static_cast<Json::UInt64>(r.started_ms); if (r.stopped_ms>0) s["stopped_at"] = static_cast<Json::UInt64>(r.stopped_ms); items.append(s); } } else { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "rest", 5000) << "sessions listRecent failed"; } } else { auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id != pipeline) continue; if (!stream.empty() && info.stream_id != stream) continue; Json::Value s(Json::objectValue); s["stream_id"] = info.stream_id; s["pipeline"] = info.profile_id; s["status"] = "Running"; s["started_at"] = now_ms; items.append(s); } } return items; };
    auto rev_now = fingerprint();
    if (!since || since != rev_now) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev_now); data["items"] = snapshot(); payload["data"] = data; return jsonResponse(payload, 200); }
    auto start = std::chrono::steady_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto cur = fingerprint();
        if (cur != since) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(cur); data["items"] = snapshot(); payload["data"] = data; return jsonResponse(payload, 200); }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
        if (elapsed >= timeout_ms) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(since); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
    }
}

} // namespace va::server
