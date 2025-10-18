            Json::Value ok = successPayload(); ok["drained"] = true; ok["name"] = name; ok["timeout_sec"] = timeout_sec; return jsonResponse(ok, 200);
        } catch (const std::exception& ex) { return errorResponse(std::string("exception: ") + ex.what(), 500); }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

      HttpResponse handleSystemInfo(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);

        const auto& config = app.appConfig();
        // Current engine (dynamic)
        auto cur = app.currentEngine();
        Json::Value engine(Json::objectValue);
        engine["type"] = cur.name;
        engine["device"] = cur.device_index;

        auto getBool = [&](const char* key, bool fallback){
            auto it = cur.options.find(key);
            if (it == cur.options.end()) return fallback;
            std::string v = toLower(it->second);
            if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
            if (v=="0"||v=="false"||v=="no"||v=="off") return false;
            return fallback;
        };
        auto getInt = [&](const char* key, int fallback){
            auto it = cur.options.find(key);
            if (it == cur.options.end()) return fallback;
            try { return std::stoi(it->second); } catch (...) { return fallback; }
        };
        auto getU64 = [&](const char* key, uint64_t fallback){
            auto it = cur.options.find(key);
            if (it == cur.options.end()) return fallback;
            try { return static_cast<uint64_t>(std::stoll(it->second)); } catch (...) { return fallback; }
        };
        auto getDbl = [&](const char* key, double fallback){
            auto it = cur.options.find(key);
            if (it == cur.options.end()) return fallback;
            try { return std::stod(it->second); } catch (...) { return fallback; }
        };

        Json::Value engine_options(Json::objectValue);
        // Core execution options
        engine_options["use_io_binding"] = getBool("use_io_binding", config.engine.options.use_io_binding);
        engine_options["prefer_pinned_memory"] = getBool("prefer_pinned_memory", config.engine.options.prefer_pinned_memory);
        engine_options["allow_cpu_fallback"] = getBool("allow_cpu_fallback", config.engine.options.allow_cpu_fallback);
        engine_options["enable_profiling"] = getBool("enable_profiling", config.engine.options.enable_profiling);
        engine_options["tensorrt_fp16"] = getBool("trt_fp16", config.engine.options.tensorrt_fp16);
        engine_options["tensorrt_int8"] = getBool("trt_int8", config.engine.options.tensorrt_int8);
        engine_options["tensorrt_workspace_mb"] = getInt("trt_workspace_mb", config.engine.options.tensorrt_workspace_mb);
        engine_options["io_binding_input_bytes"] = static_cast<Json::UInt64>(getU64("io_binding_input_bytes", config.engine.options.io_binding_input_bytes));
        engine_options["io_binding_output_bytes"] = static_cast<Json::UInt64>(getU64("io_binding_output_bytes", config.engine.options.io_binding_output_bytes));
          // Source/decoder/renderer toggles
          engine_options["use_ffmpeg_source"] = getBool("use_ffmpeg_source", false);
          engine_options["use_nvdec"] = getBool("use_nvdec", false);
          engine_options["use_nvenc"] = getBool("use_nvenc", false);
          engine_options["use_cuda_preproc"] = getBool("use_cuda_preproc", false);
          // Multistage toggles
          engine_options["use_multistage"] = getBool("use_multistage", false);
          {
              auto it = cur.options.find("graph_id");
