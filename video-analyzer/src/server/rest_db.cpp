#include "server/rest_impl.hpp"

namespace va::server {

// --- Database: health check ---
HttpResponse RestServer::Impl::handleDbPing(const HttpRequest&) {
    Json::Value payload;
    bool ok = false;
    std::string err;
    if (db_pool && db_pool->valid()) {
        ok = db_pool->ping(&err);
    } else {
        err = "database disabled";
    }
    payload["ok"] = ok;
    if (!ok && !err.empty()) payload["error"] = err;
    return jsonResponse(payload, ok ? 200 : 503);
}

HttpResponse RestServer::Impl::handleDbPurge(const HttpRequest& req) {
    try {
        Json::Value body = parseJson(req.body);
        uint64_t events_sec = 0, logs_sec = 0;
        if (body.isMember("events_seconds") && body["events_seconds"].isUInt64()) events_sec = body["events_seconds"].asUInt64();
        if (body.isMember("logs_seconds") && body["logs_seconds"].isUInt64()) logs_sec = body["logs_seconds"].asUInt64();
        if (events_sec==0 && logs_sec==0) return errorResponse("missing events_seconds/logs_seconds", 400);
        Json::Value payload = successPayload(); Json::Value res(Json::objectValue);
        if (events_sec>0 && events_repo) { std::string err; bool ok = events_repo->purgeOlderThanSeconds(events_sec, &err); res["events_ok"] = ok; if(!ok) res["events_error"]=err; }
        if (logs_sec>0 && logs_repo)   { std::string err; bool ok = logs_repo->purgeOlderThanSeconds(logs_sec, &err);   res["logs_ok"] = ok;   if(!ok) res["logs_error"]=err; }
        payload["data"] = res; return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

HttpResponse RestServer::Impl::handleDbRetentionStatus(const HttpRequest&) {
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    Json::Value cfg(Json::objectValue);
    const auto& r = app.appConfig().database.retention;
    cfg["enabled"] = r.enabled;
    cfg["events_seconds"] = static_cast<Json::UInt64>(r.events_seconds);
    cfg["logs_seconds"] = static_cast<Json::UInt64>(r.logs_seconds);
    cfg["interval_seconds"] = static_cast<Json::UInt64>(r.interval_seconds);
    cfg["jitter_percent"] = r.jitter_percent;
    Json::Value m(Json::objectValue);
    m["runs_total"] = static_cast<Json::UInt64>(retention_runs_total.load(std::memory_order_relaxed));
    m["failures_total"] = static_cast<Json::UInt64>(retention_failures_total.load(std::memory_order_relaxed));
    m["last_ms"] = static_cast<Json::UInt64>(retention_last_ms.load(std::memory_order_relaxed));
    data["config"] = cfg; data["metrics"] = m; payload["data"] = data; return jsonResponse(payload, 200);
}

} // namespace va::server
