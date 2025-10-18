        data["ffmpeg_enabled"] = app.ffmpegEnabled();
        data["model_count"] = static_cast<Json::UInt64>(app.detectionModels().size());
        data["profile_count"] = static_cast<Json::UInt64>(app.profiles().size());

        const auto runtime_status = app.engineRuntimeStatus();
        Json::Value runtime(Json::objectValue);
        runtime["provider"] = runtime_status.provider;
        runtime["gpu_active"] = runtime_status.gpu_active;
        runtime["io_binding"] = runtime_status.io_binding;
        runtime["device_binding"] = runtime_status.device_binding;
        runtime["cpu_fallback"] = runtime_status.cpu_fallback;
        data["engine_runtime"] = runtime;

          payload["data"] = data;
          return jsonResponse(payload, 200);
      }
      // --- Multistage graph helpers ---
      static std::vector<std::filesystem::path> graphDirCandidates() {
          std::vector<std::filesystem::path> unique;
          std::unordered_set<std::string> seen;
          auto add_dir = [&](const std::filesystem::path& p){
              std::error_code ec; auto can = std::filesystem::weakly_canonical(p, ec);
              const std::string key = ec ? p.string() : can.string();
              if (!seen.count(key)) { seen.insert(key); unique.push_back(ec ? p : can); }
          };
          std::filesystem::path exe_dir = std::filesystem::current_path();
          add_dir(std::filesystem::current_path() / "config" / "graphs");
          add_dir(exe_dir / "config" / "graphs");
          auto curd = exe_dir;
          for (int i=0;i<6;++i) {
              add_dir(curd / "config" / "graphs");
              add_dir(curd / "video-analyzer" / "config" / "graphs");
              if (curd.has_parent_path()) curd = curd.parent_path(); else break;
          }
          return unique;
      }

      HttpResponse handleGraphsList(const HttpRequest& /*req*/) {
          // DB-only: read from graphs table
          if (!db_pool || !db_pool->valid() || !graphs_repo) {
              return errorResponse("database disabled", 503);
          }
          std::vector<va::storage::GraphRow> rows;
          std::string err;
          if (!graphs_repo->listAll(&rows, &err)) {
              return errorResponse(err.empty()? std::string("failed to list graphs") : err, 500);
          }
          Json::Value payload = successPayload();
          Json::Value arr(Json::arrayValue);
          for (const auto& r : rows) {
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
