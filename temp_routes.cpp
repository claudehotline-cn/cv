            return resp;
        });

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
        server.addRoute("GET", "/sources/watch", sourcesWatchHandler);
        server.addRoute("GET", "/api/sources/watch", sourcesWatchHandler);
        // SSE variants (experimental): watch via EventSource
        // server.addStreamRoute("GET", "/api/sources/watch_sse", [this](int fd, const HttpRequest& req){ streamSourcesSSE(fd, req); });

        // Prometheus metrics endpoint
        auto metricsHandler = [this](const HttpRequest& req) { return handleMetrics(req); };
        server.addRoute("GET", "/metrics", metricsHandler);
        auto metricsCfgGet = [this](const HttpRequest& req) { return handleMetricsConfigGet(req); };
        auto metricsCfgSet = [this](const HttpRequest& req) { return handleMetricsConfigSet(req); };
        server.addRoute("GET", "/api/metrics", metricsCfgGet);
        server.addRoute("POST", "/api/metrics/set", metricsCfgSet);

        // Observability: logs/events
        auto logsRecentHandler = [this](const HttpRequest& req) { return handleLogsRecent(req); };
        auto logsWatchHandler  = [this](const HttpRequest& req) { return handleLogsWatch(req); };
        auto eventsRecentHandler = [this](const HttpRequest& req) { return handleEventsRecent(req); };
        auto eventsWatchHandler  = [this](const HttpRequest& req) { return handleEventsWatch(req); };
        auto sessionsWatchHandler = [this](const HttpRequest& req) { return handleSessionsWatch(req); };
        server.addRoute("GET", "/api/logs", logsRecentHandler);
        server.addRoute("GET", "/api/logs/watch", logsWatchHandler);
        // SSE: logs (can be disabled by VA_DISABLE_SSE=1)
        {
            const char* _va_disable_sse = std::getenv("VA_DISABLE_SSE");
            const bool sse_enabled = !(_va_disable_sse && std::string(_va_disable_sse) == "1");
            if (sse_enabled) {
                server.addStreamRoute("GET", "/api/logs/watch_sse", [this](int fd, const HttpRequest& req){ streamLogsSSE(fd, req); });
            }
        }
        server.addRoute("GET", "/api/events/recent", eventsRecentHandler);
        server.addRoute("GET", "/api/events/watch", eventsWatchHandler);
        server.addRoute("GET", "/api/sessions/watch", sessionsWatchHandler);
        // SSE: events (can be disabled by VA_DISABLE_SSE=1)
        {
            const char* _va_disable_sse = std::getenv("VA_DISABLE_SSE");
            const bool sse_enabled = !(_va_disable_sse && std::string(_va_disable_sse) == "1");
            if (sse_enabled) {
                server.addStreamRoute("GET", "/api/events/watch_sse", [this](int fd, const HttpRequest& req){ streamEventsSSE(fd, req); });
