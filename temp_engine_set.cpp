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

    HttpResponse handleParamsUpdate(const HttpRequest& req) {
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

      HttpResponse handleSetEngine(const HttpRequest& req) {
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

      HttpResponse handleSources(const HttpRequest& req) {
          // DB-only listing of sources; on failure, return error for frontend to显示
          if (!sources_repo) {
              return errorResponse("database disabled", 503);
          }
          // Parse pagination
          auto q = parseQueryKV(req.query);
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...){ return def; } };
          auto page = get_int("page", 1);
