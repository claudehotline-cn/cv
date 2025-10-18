
    HttpResponse handleSubscribe(const HttpRequest& req) {
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

    HttpResponse handleUnsubscribe(const HttpRequest& req) {
        try {
            const Json::Value body = parseJson(req.body);

            auto stream_opt = getStringField(body, {"stream_id", "stream"});
