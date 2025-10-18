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
