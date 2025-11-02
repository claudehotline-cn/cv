#include "server/rest_impl.hpp"
#include "core/logger.hpp"

namespace va::server {

void RestServer::Impl::registerRoutes() {
#if defined(VA_DISABLE_HTTP_PUBLIC)
    // Public HTTP routes disabled: expose only Prometheus metrics and WHEP negotiation endpoints.
    // Metrics endpoints
    auto metricsHandler = [this](const HttpRequest& req) { return handleMetrics(req); };
    server.addRoute("GET", "/metrics", metricsHandler);
    server.addRoute("OPTIONS", "/metrics", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });
    auto metricsCfgGet = [this](const HttpRequest& req) { return handleMetricsConfigGet(req); };
    auto metricsCfgSet = [this](const HttpRequest& req) { return handleMetricsConfigSet(req); };
    server.addRoute("GET", "/api/metrics", metricsCfgGet);
    server.addRoute("POST", "/api/metrics/set", metricsCfgSet);

    // WHEP negotiation (create/patch/delete) + CORS
    auto whepCreateHandler = [this](const HttpRequest& req) { return handleWhepCreate(req); };
    auto whepPatchHandler  = [this](const HttpRequest& req) { return handleWhepPatch(req); };
    auto whepDeleteHandler = [this](const HttpRequest& req) { return handleWhepDelete(req); };
    auto whepCorsHandler   = [this](const HttpRequest& req) { return handleWhepCors(req); };
    server.addRoute("POST",   "/whep", whepCreateHandler);
    server.addRoute("PATCH",  "/whep/sessions/:sid", whepPatchHandler);
    server.addRoute("DELETE", "/whep/sessions/:sid", whepDeleteHandler);
    server.addRoute("OPTIONS", "/whep", whepCorsHandler);
    server.addRoute("OPTIONS", "/whep/sessions/:sid", whepCorsHandler);

    // Control: set pipeline analysis mode (CP-only, minimal)
    server.addRoute("POST", "/api/control/pipeline_mode", [this](const HttpRequest& req){
        try {
            Json::Value j = parseJson(req.body);
            auto sid = getStringField(j, {"stream_id","stream"});
            auto pid = getStringField(j, {"profile","pipeline","profile_id"});
            bool enabled = true;
            if (j.isMember("analysis_enabled")) enabled = j["analysis_enabled"].asBool();
            if (!sid || !pid) { return errorResponse("missing stream/profile", 400); }
            VA_LOG_INFO() << "[REST] /api/control/pipeline_mode recv stream='" << *sid
                          << "' profile='" << *pid << "' enabled=" << (enabled?"true":"false");
            bool ok = false;
            try {
                ok = app.trackManager()->setAnalysisEnabled(*sid, *pid, enabled);
            } catch (...) { ok = false; }
            if (!ok) return errorResponse("not found", 404);
            VA_LOG_INFO() << "[REST] pipeline_mode applied OK stream='" << *sid << "' profile='" << *pid << "'";
            HttpResponse r; r.status_code=200; r.body = "{\"code\":\"OK\"}"; return r;
        } catch (const std::exception& ex) {
            return errorResponse(std::string("invalid json: ")+ex.what(), 400);
        }
    });
    server.addRoute("OPTIONS", "/api/control/pipeline_mode", [](const HttpRequest&){ HttpResponse r; r.status_code=204; return r; });

#if defined(VA_REST_DEPRECATED_410)
    // Deprecated VA REST endpoints placeholders (410 Gone), to guide callers to Controlplane
    auto gone = [](const HttpRequest&) {
        HttpResponse resp; resp.status_code = 410;
        resp.headers["Access-Control-Allow-Origin"] = "*";
        resp.headers["Access-Control-Expose-Headers"] = "Location";
        resp.headers["Location"] = "/";
        resp.body = "{\"code\":\"GONE\",\"msg\":\"moved to controlplane\"}";
        return resp;
    };
    // Subscriptions
    server.addRoute("POST",  "/api/subscriptions", gone);
    server.addRoute("GET",   "/api/subscriptions/:id", gone);
    server.addRoute("DELETE","/api/subscriptions/:id", gone);
    server.addRoute("GET",   "/api/subscriptions/:id/events", gone);
    // Sources
    server.addRoute("GET",   "/api/sources", gone);
    server.addRoute("GET",   "/api/sources/watch", gone);
    server.addRoute("GET",   "/api/sources/watch_sse", gone);
    // Control API
    server.addRoute("POST",  "/api/control/apply_pipeline", gone);
    server.addRoute("POST",  "/api/control/apply_pipelines", gone);
    server.addRoute("POST",  "/api/control/hotswap", gone);
    server.addRoute("DELETE","/api/control/pipeline", gone);
    server.addRoute("GET",   "/api/control/status", gone);
    server.addRoute("POST",  "/api/control/drain", gone);
    // Orchestration
    server.addRoute("POST",  "/api/orch/attach_apply", gone);
    server.addRoute("POST",  "/api/orch/detach_remove", gone);
    server.addRoute("GET",   "/api/orch/health", gone);
    // System
    server.addRoute("GET",   "/api/system/info", gone);
#endif // VA_REST_DEPRECATED_410
    return;
#else
    server.addRoute("POST", "/api/subscriptions", [this](const HttpRequest& req) {
        return handleSubscriptionCreate(req);
    });
    server.addRoute("GET", "/api/subscriptions/:id", [this](const HttpRequest& req) {
        auto it = req.params.find("id");
        if (it == req.params.end()) return errorResponse("missing id", 400);
        return handleSubscriptionGet(req, it->second);
    });
    server.addRoute("DELETE", "/api/subscriptions/:id", [this](const HttpRequest& req) {
        auto it = req.params.find("id");
        if (it == req.params.end()) return errorResponse("missing id", 400);
        return handleSubscriptionDelete(req, it->second);
    });

    // SSE: subscription phase events
    server.addStreamRoute("GET", "/api/subscriptions/:id/events", [this](int fd, const HttpRequest& req) {
        auto it = req.params.find("id");
        if (it == req.params.end()) { return; }
        streamSubscriptionSSE(fd, req, it->second);
    });

    auto subscribeHandler = [this](const HttpRequest& req) { return handleSubscribe(req); };
    auto unsubscribeHandler = [this](const HttpRequest& req) { return handleUnsubscribe(req); };
    auto corsHandler = [](const HttpRequest& /*req*/) {
        HttpResponse resp; resp.status_code = 204;
        resp.headers["Access-Control-Allow-Origin"] = "*";
        resp.headers["Access-Control-Allow-Methods"] = "GET,POST,PUT,DELETE,OPTIONS,PATCH";
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type,Authorization";
        resp.body.clear();
        return resp;
    };
    auto sourceSwitchHandler = [this](const HttpRequest& req) { return handleSourceSwitch(req); };
    auto modelSwitchHandler = [this](const HttpRequest& req) { return handleModelSwitch(req); };
    auto taskSwitchHandler = [this](const HttpRequest& req) { return handleTaskSwitch(req); };
    auto paramsUpdateHandler = [this](const HttpRequest& req) { return handleParamsUpdate(req); };
    auto setEngineHandler = [this](const HttpRequest& req) { return handleSetEngine(req); };
    auto graphsListHandler = [this](const HttpRequest& req) { return handleGraphsList(req); };
    auto graphSwitchHandler = [this](const HttpRequest& req) { return handleGraphSwitch(req); };
    // Control-plane (embedded): ApplyPipeline / ApplyPipelines via REST
    auto cpApplyHandler = [this](const HttpRequest& req) { return handleCpApply(req); };
    auto cpApplyBatchHandler = [this](const HttpRequest& req) { return handleCpApplyBatch(req); };
    auto cpHotSwapHandler = [this](const HttpRequest& req) { return handleCpHotSwap(req); };
    auto cpRemoveHandler = [this](const HttpRequest& req) { return handleCpRemove(req); };
    auto cpStatusHandler = [this](const HttpRequest& req) { return handleCpStatus(req); };
    auto cpDrainHandler  = [this](const HttpRequest& req) { return handleCpDrain(req); };

    server.addRoute("POST", "/subscribe", subscribeHandler);
    server.addRoute("POST", "/api/subscribe", subscribeHandler);
    server.addRoute("OPTIONS", "/api/subscribe", corsHandler);

    server.addRoute("POST", "/unsubscribe", unsubscribeHandler);
    server.addRoute("POST", "/api/unsubscribe", unsubscribeHandler);
    server.addRoute("OPTIONS", "/api/unsubscribe", corsHandler);

    server.addRoute("POST", "/source/switch", sourceSwitchHandler);
    server.addRoute("POST", "/api/source/switch", sourceSwitchHandler);

    server.addRoute("POST", "/model/switch", modelSwitchHandler);
    server.addRoute("POST", "/api/model/switch", modelSwitchHandler);

    server.addRoute("POST", "/task/switch", taskSwitchHandler);
    server.addRoute("POST", "/api/task/switch", taskSwitchHandler);

    server.addRoute("PATCH", "/model/params", paramsUpdateHandler);
    server.addRoute("PATCH", "/api/model/params", paramsUpdateHandler);

    server.addRoute("POST", "/engine/set", setEngineHandler);
    server.addRoute("POST", "/api/engine/set", setEngineHandler);

    // Multistage graph management
    server.addRoute("GET", "/api/graphs", graphsListHandler);
    // Preflight compatibility check
    auto preflightHandler = [this](const HttpRequest& req) { return handlePreflight(req); };
    server.addRoute("POST", "/api/preflight", preflightHandler);
    server.addRoute("POST", "/api/graph/set", graphSwitchHandler);
    // Control-plane mapping
    // CP routes with metrics wrapping
    server.addRoute("POST", "/api/control/apply_pipeline", [this, cpApplyHandler](const HttpRequest& req) {
        auto t0 = std::chrono::steady_clock::now();
        auto resp = cpApplyHandler(req);
        // For compatibility with VSM HTTP client expecting 200, map 202->200 during test phase
        if (resp.status_code == 202) resp.status_code = 200;
        recordCpMetric("apply", resp.status_code, t0);
        return resp;
    });
    server.addRoute("POST", "/api/control/apply_pipelines", [this, cpApplyBatchHandler](const HttpRequest& req) {
        auto t0 = std::chrono::steady_clock::now();
        auto resp = cpApplyBatchHandler(req);
        recordCpMetric("apply_batch", resp.status_code, t0);
        return resp;
    });
    server.addRoute("POST", "/api/control/hotswap", [this, cpHotSwapHandler](const HttpRequest& req) {
        auto t0 = std::chrono::steady_clock::now();
        auto resp = cpHotSwapHandler(req);
        recordCpMetric("hotswap", resp.status_code, t0);
        return resp;
    });
    server.addRoute("DELETE", "/api/control/pipeline", [this, cpRemoveHandler](const HttpRequest& req) {
        auto t0 = std::chrono::steady_clock::now();
        auto resp = cpRemoveHandler(req);
        recordCpMetric("remove", resp.status_code, t0);
        return resp;
    });
    server.addRoute("GET", "/api/control/status", cpStatusHandler);
    server.addRoute("POST", "/api/control/drain", [this, cpDrainHandler](const HttpRequest& req) {
        auto t0 = std::chrono::steady_clock::now();
        auto resp = cpDrainHandler(req);
        recordCpMetric("drain", resp.status_code, t0);
        return resp;
    });

    // Control: set pipeline analysis mode (keep available when public HTTP is enabled)
    server.addRoute("POST", "/api/control/pipeline_mode", [this](const HttpRequest& req){
        try {
            Json::Value j = parseJson(req.body);
            auto sid = getStringField(j, {"stream_id","stream"});
            auto pid = getStringField(j, {"profile","pipeline","profile_id"});
            bool enabled = true;
            if (j.isMember("analysis_enabled")) enabled = j["analysis_enabled"].asBool();
            if (!sid || !pid) { return errorResponse("missing stream/profile", 400); }
            VA_LOG_INFO() << "[REST] /api/control/pipeline_mode recv stream='" << *sid
                          << "' profile='" << *pid << "' enabled=" << (enabled?"true":"false");
            bool ok = false;
            try {
                ok = app.trackManager()->setAnalysisEnabled(*sid, *pid, enabled);
            } catch (...) { ok = false; }
            if (!ok) return errorResponse("not found", 404);
            VA_LOG_INFO() << "[REST] pipeline_mode applied OK stream='" << *sid << "' profile='" << *pid << "'";
            HttpResponse r; r.status_code=200; r.body = "{\"code\":\"OK\"}"; return r;
        } catch (const std::exception& ex) {
            return errorResponse(std::string("invalid json: ")+ex.what(), 400);
        }
    });
    server.addRoute("OPTIONS", "/api/control/pipeline_mode", [](const HttpRequest&){ HttpResponse r; r.status_code=204; return r; });

    // Logging config: runtime set
    auto loggingSetHandler = [this](const HttpRequest& req) { return handleLoggingSet(req); };
    auto loggingGetHandler = [this](const HttpRequest& req) { return handleLoggingGet(req); };
    server.addRoute("POST", "/api/logging/set", loggingSetHandler);
    server.addRoute("GET", "/api/logging", loggingGetHandler);

    auto systemInfoHandler = [this](const HttpRequest& req) { return handleSystemInfo(req); };
    auto systemStatsHandler = [this](const HttpRequest& req) { return handleSystemStats(req); };
    auto modelsHandler = [this](const HttpRequest& req) { return handleModels(req); };
    auto profilesHandler = [this](const HttpRequest& req) { return handleProfiles(req); };
    auto pipelinesHandler = [this](const HttpRequest& req) { return handlePipelines(req); };

    server.addRoute("GET", "/system/info", systemInfoHandler);
    server.addRoute("GET", "/api/system/info", systemInfoHandler);
    server.addRoute("OPTIONS", "/api/system/info", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });

    server.addRoute("GET", "/system/stats", systemStatsHandler);
    server.addRoute("GET", "/api/system/stats", systemStatsHandler);

    server.addRoute("GET", "/models", modelsHandler);
    server.addRoute("GET", "/api/models", modelsHandler);

    server.addRoute("GET", "/profiles", profilesHandler);
    server.addRoute("GET", "/api/profiles", profilesHandler);

    server.addRoute("GET", "/pipelines", pipelinesHandler);
    server.addRoute("GET", "/api/pipelines", pipelinesHandler);

    // Aggregated sources view + long-poll watch
    auto sourcesHandler = [this](const HttpRequest& req) { return handleSources(req); };
    auto sourcesWatchHandler = [this](const HttpRequest& req) { return handleSourcesWatch(req); };
    server.addRoute("GET", "/sources", sourcesHandler);
    server.addRoute("GET", "/api/sources", sourcesHandler);
    server.addRoute("OPTIONS", "/api/sources", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });
    server.addRoute("GET", "/sources/watch", sourcesWatchHandler);
    server.addRoute("GET", "/api/sources/watch", sourcesWatchHandler);
    // SSE: sources
    server.addStreamRoute("GET", "/api/sources/watch_sse", [this](int fd, const HttpRequest& req) { streamSourcesSSE(fd, req); });

    // Prometheus metrics endpoint
    auto metricsHandler = [this](const HttpRequest& req) { return handleMetrics(req); };
    server.addRoute("GET", "/metrics", metricsHandler);
    server.addRoute("OPTIONS", "/metrics", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });
    auto metricsCfgGet = [this](const HttpRequest& req) { return handleMetricsConfigGet(req); };
    auto metricsCfgSet = [this](const HttpRequest& req) { return handleMetricsConfigSet(req); };
    server.addRoute("GET", "/api/metrics", metricsCfgGet);
    server.addRoute("POST", "/api/metrics/set", metricsCfgSet);

    // Admin: WAL evidence endpoints (read-only)
    auto walSummaryHandler = [this](const HttpRequest& req) { return handleWalSummary(req); };
    auto walTailHandler    = [this](const HttpRequest& req) { return handleWalTail(req); };
    server.addRoute("GET", "/api/admin/wal/summary", walSummaryHandler);
    server.addRoute("GET", "/api/admin/wal/tail", walTailHandler);

    // Observability: logs/events
    auto logsRecentHandler = [this](const HttpRequest& req) { return handleLogsRecent(req); };
    auto logsWatchHandler  = [this](const HttpRequest& req) { return handleLogsWatch(req); };
    auto eventsRecentHandler = [this](const HttpRequest& req) { return handleEventsRecent(req); };
    auto eventsWatchHandler  = [this](const HttpRequest& req) { return handleEventsWatch(req); };
    auto sessionsWatchHandler = [this](const HttpRequest& req) { return handleSessionsWatch(req); };
    server.addRoute("GET", "/api/logs", logsRecentHandler);
    server.addRoute("OPTIONS", "/api/logs", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });
    server.addRoute("GET", "/api/logs/watch", logsWatchHandler);
    // SSE: logs
    server.addStreamRoute("GET", "/api/logs/watch_sse", [this](int fd, const HttpRequest& req) { streamLogsSSE(fd, req); });
    server.addRoute("GET", "/api/events/recent", eventsRecentHandler);
    server.addRoute("OPTIONS", "/api/events/recent", [](const HttpRequest&) { HttpResponse r; r.status_code=204; return r; });
    server.addRoute("GET", "/api/events/watch", eventsWatchHandler);
    server.addRoute("GET", "/api/sessions/watch", sessionsWatchHandler);
    // SSE: events
    server.addStreamRoute("GET", "/api/events/watch_sse", [this](int fd, const HttpRequest& req) { streamEventsSSE(fd, req); });

    // Database: health check
    auto dbPingHandler = [this](const HttpRequest& req) { return handleDbPing(req); };
    server.addRoute("GET", "/api/db/ping", dbPingHandler);

    // Retention: status + manual purge endpoint (admin)
    auto dbPurgeHandler = [this](const HttpRequest& req) { return handleDbPurge(req); };
    auto dbRetentionStatusHandler = [this](const HttpRequest& req) { return handleDbRetentionStatus(req); };
    server.addRoute("GET",  "/api/db/retention/status", dbRetentionStatusHandler);
    server.addRoute("POST", "/api/db/retention/purge", dbPurgeHandler);

    // Sessions: list recent
    auto sessionsListHandler = [this](const HttpRequest& req) { return handleSessionsList(req); };
    server.addRoute("GET", "/api/sessions", sessionsListHandler);

    // Orchestration endpoints moved into embedded Control Plane (from VSM)
    auto orchAttachApplyHandler = [this](const HttpRequest& req) { return handleOrchAttachApply(req); };
    auto orchDetachRemoveHandler = [this](const HttpRequest& req) { return handleOrchDetachRemove(req); };
    auto orchHealthHandler = [this](const HttpRequest& req) { return handleOrchHealth(req); };
    server.addRoute("POST", "/api/orch/attach_apply", orchAttachApplyHandler);
    server.addRoute("POST", "/api/orch/detach_remove", orchDetachRemoveHandler);
    server.addRoute("GET",  "/api/orch/health", orchHealthHandler);

    // WHEP negotiation (Control Plane hosted)
    auto whepCreateHandler = [this](const HttpRequest& req) { return handleWhepCreate(req); };
    auto whepPatchHandler  = [this](const HttpRequest& req) { return handleWhepPatch(req); };
    auto whepDeleteHandler = [this](const HttpRequest& req) { return handleWhepDelete(req); };
    auto whepCorsHandler   = [this](const HttpRequest& req) { return handleWhepCors(req); };
    server.addRoute("POST",   "/whep", whepCreateHandler);
    server.addRoute("PATCH",  "/whep/sessions/:sid", whepPatchHandler);
    server.addRoute("DELETE", "/whep/sessions/:sid", whepDeleteHandler);
    server.addRoute("OPTIONS", "/whep", whepCorsHandler);
    server.addRoute("OPTIONS", "/whep/sessions/:sid", whepCorsHandler);
#endif // VA_DISABLE_HTTP_PUBLIC
}

} // namespace va::server

