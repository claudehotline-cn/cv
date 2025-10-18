        // SSE: events (can be disabled by VA_DISABLE_SSE=1)
        {
            const char* _va_disable_sse = std::getenv("VA_DISABLE_SSE");
            const bool sse_enabled = !(_va_disable_sse && std::string(_va_disable_sse) == "1");
            if (sse_enabled) {
                server.addStreamRoute("GET", "/api/events/watch_sse", [this](int fd, const HttpRequest& req){ streamEventsSSE(fd, req); });
            }
        }

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
    }

    bool start() {
        return server.start();
    }

    void stop() {
        server.stop();
