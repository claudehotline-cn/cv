              auto it = cur.options.find("graph_id");
              engine_options["graph_id"] = (it != cur.options.end()) ? Json::Value(it->second) : Json::Value("");
          }
        // Rendering / postproc toggles
        engine_options["render_cuda"] = getBool("render_cuda", false);
        engine_options["render_passthrough"] = getBool("render_passthrough", false);
        engine_options["use_cuda_nms"] = getBool("use_cuda_nms", false);
        // Overlay tuning
        engine_options["overlay_thickness"] = getInt("overlay_thickness", 0);
        engine_options["overlay_alpha"] = getDbl("overlay_alpha", 0.0);
        engine_options["overlay_draw_labels"] = getBool("overlay_draw_labels", true);
        // IoBinding output policies
        engine_options["stage_device_outputs"] = getBool("stage_device_outputs", false);
        engine_options["device_output_views"] = getBool("device_output_views", false);
        // Warmup controls: echo string "auto" if configured as such, else int
        {
            auto it = cur.options.find("warmup_runs");
            if (it != cur.options.end()) {
                std::string v = toLower(it->second);
                if (v == "auto") {
                    engine_options["warmup_runs"] = "auto";
                } else {
                    engine_options["warmup_runs"] = getInt("warmup_runs", 1);
                }
            } else {
                engine_options["warmup_runs"] = 1;
            }
        }

        engine["options"] = engine_options;
        data["engine"] = engine;

        // Also expose static config as engine_config for reference
        Json::Value engine_cfg(Json::objectValue);
        engine_cfg["type"] = config.engine.type;
        engine_cfg["device"] = config.engine.device;
        Json::Value cfg_opts(Json::objectValue);
        cfg_opts["use_io_binding"] = config.engine.options.use_io_binding;
        cfg_opts["prefer_pinned_memory"] = config.engine.options.prefer_pinned_memory;
        cfg_opts["allow_cpu_fallback"] = config.engine.options.allow_cpu_fallback;
        cfg_opts["enable_profiling"] = config.engine.options.enable_profiling;
        cfg_opts["tensorrt_fp16"] = config.engine.options.tensorrt_fp16;
        cfg_opts["tensorrt_int8"] = config.engine.options.tensorrt_int8;
        cfg_opts["tensorrt_workspace_mb"] = config.engine.options.tensorrt_workspace_mb;
        cfg_opts["io_binding_input_bytes"] = static_cast<Json::UInt64>(config.engine.options.io_binding_input_bytes);
        cfg_opts["io_binding_output_bytes"] = static_cast<Json::UInt64>(config.engine.options.io_binding_output_bytes);
        engine_cfg["options"] = cfg_opts;
        data["engine_config"] = engine_cfg;

        Json::Value observability(Json::objectValue);
        observability["log_level"] = config.observability.log_level;
        observability["console"] = config.observability.console;
        observability["file_path"] = config.observability.file_path;
        observability["file_max_size_kb"] = config.observability.file_max_size_kb;
        observability["file_max_files"] = config.observability.file_max_files;
        observability["pipeline_metrics_enabled"] = config.observability.pipeline_metrics_enabled;
        observability["pipeline_metrics_interval_ms"] = config.observability.pipeline_metrics_interval_ms;
        Json::Value metrics_flags(Json::objectValue);
        metrics_flags["registry_enabled"] = config.observability.metrics_registry_enabled;
        metrics_flags["extended_labels"] = config.observability.metrics_extended_labels;
        observability["metrics"] = metrics_flags;
        data["observability"] = observability;

        Json::Value sfu(Json::objectValue);
        sfu["whip_base"] = config.sfu_whip_base;
        sfu["whep_base"] = config.sfu_whep_base;
        data["sfu"] = sfu;

        // Database summary (no secrets)
        {
            const auto& dbc = app.appConfig().database;
            Json::Value db(Json::objectValue);
            db["driver"] = dbc.driver;
            db["host"] = dbc.host;
            db["port"] = dbc.port;
            db["db"] = dbc.db;
            if (!dbc.user.empty()) db["user"] = "***";
            data["database"] = db;
        }

        data["ffmpeg_enabled"] = app.ffmpegEnabled();
