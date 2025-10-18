              Json::Value node(Json::objectValue);
              node["id"] = r.id;
              node["name"] = r.name;
              if (!r.requires_json.empty()) {
                  try {
                      Json::CharReaderBuilder b; std::string errs; std::istringstream iss(r.requires_json); Json::Value req;
                      if (Json::parseFromStream(b, iss, &req, &errs)) node["requires"] = req;
                  } catch (...) { /* ignore bad requires */ }
              }
              arr.append(node);
          }
          payload["data"] = arr;
          return jsonResponse(payload, 200);
      }

      HttpResponse handleGraphSwitch(const HttpRequest& req) {
          try {
              const Json::Value body = parseJson(req.body);
              if (!body.isMember("graph_id") || !body["graph_id"].isString()) {
                  return errorResponse("Missing required field: graph_id", 400);
              }
              std::string graph_id = body["graph_id"].asString();
              auto curEng = app.currentEngine();
              va::core::EngineDescriptor desc = curEng;
              desc.options["use_multistage"] = "true";
              desc.options["graph_id"] = graph_id;
              if (!app.setEngine(desc)) {
                  return errorResponse(app.lastError().empty() ? "graph switch failed" : app.lastError(), 400);
              }
              VA_LOG_C(::va::core::LogLevel::Info, "rest") << "Graph switched at runtime to id='" << graph_id << "' via /api/graph/set";
              Json::Value payload = successPayload();
              payload["graph_id"] = graph_id;
              emitEvent("info", "graph_switch", std::string(), "control", std::string(), std::string("graph_id=") + graph_id);
              emitLog("info", std::string(), "control", std::string(), std::string("graph_switch ") + graph_id);
