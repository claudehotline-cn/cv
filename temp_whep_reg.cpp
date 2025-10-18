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
