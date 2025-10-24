#include "server/rest_impl.hpp"
#include "analyzer/model_registry.hpp"
#include "core/wal.hpp"

namespace va::server {

HttpResponse RestServer::Impl::handleSystemInfo(const HttpRequest& /*req*/) {
  Json::Value payload = successPayload();
  Json::Value data(Json::objectValue);

  const auto& config = app.appConfig();
  // Current engine (dynamic)
  auto cur = app.currentEngine();
  Json::Value engine(Json::objectValue);
  engine["type"] = cur.name;
  engine["device"] = cur.device_index;

  auto getBool = [&](const char* key, bool fallback) {
      auto it = cur.options.find(key);
      if (it == cur.options.end()) return fallback;
      std::string v = toLower(it->second);
      if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
      if (v=="0"||v=="false"||v=="no"||v=="off") return false;
      return fallback;
  };
  auto getInt = [&](const char* key, int fallback) {
      auto it = cur.options.find(key);
      if (it == cur.options.end()) return fallback;
      try { return std::stoi(it->second); } catch (...) { return fallback; }
  };
  auto getU64 = [&](const char* key, uint64_t fallback) {
      auto it = cur.options.find(key);
      if (it == cur.options.end()) return fallback;
      try { return static_cast<uint64_t>(std::stoll(it->second)); } catch (...) { return fallback; }
  };
  auto getDbl = [&](const char* key, double fallback) {
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

  // Subscriptions configuration snapshot（含来源回显）
  Json::Value subs(Json::objectValue);
  subs["heavy_slots"] = subscriptions ? subscriptions->heavySlots() : 0;
  subs["model_slots"] = subscriptions ? subscriptions->modelSlots() : 0;
  subs["rtsp_slots"] = subscriptions ? subscriptions->rtspSlots() : 0;
  subs["max_queue"] = static_cast<Json::UInt64>(subscriptions ? subscriptions->maxQueue() : 0);
  subs["ttl_seconds"] = subscriptions ? subscriptions->ttlSeconds() : 0;
  Json::Value src(Json::objectValue);
  src["heavy_slots"] = subs_src_heavy;
  src["model_slots"] = subs_src_model;
  src["rtsp_slots"]  = subs_src_rtsp;
  src["max_queue"]   = subs_src_queue;
  src["ttl_seconds"] = subs_src_ttl;
  subs["source"] = src;
  data["subscriptions"] = subs;

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
  // Registry preheat and WAL status (M1)
  try {
    auto& mr = va::analyzer::ModelRegistry::instance();
    Json::Value reg(Json::objectValue);
    Json::Value pre(Json::objectValue);
    pre["enabled"] = mr.preheatEnabled();
    pre["concurrency"] = mr.preheatConcurrency();
    {
      Json::Value lst(Json::arrayValue);
      for (const auto& id : mr.preheatList()) lst.append(id);
      pre["list"] = lst;
    }
    pre["status"] = mr.preheatStatus();
    pre["warmed"] = mr.warmedCount();
    reg["preheat"] = pre;
    data["registry"] = reg;
  } catch (...) { /* ignore */ }
  try {
    Json::Value wal(Json::objectValue);
    wal["enabled"] = va::core::wal::enabled();
    wal["failed_restart"] = static_cast<Json::UInt64>(va::core::wal::failedRestartCount());
    data["wal"] = wal;
  } catch (...) { /* ignore */ }

  payload["data"] = data;
  return jsonResponse(payload, 200);
}

// --- Multistage graph helpers ---
std::vector<std::filesystem::path> RestServer::Impl::graphDirCandidates() {
    std::vector<std::filesystem::path> unique;
    std::unordered_set<std::string> seen;
    auto add_dir = [&](const std::filesystem::path& p) {
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

HttpResponse RestServer::Impl::handleGraphsList(const HttpRequest& /*req*/) {
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

HttpResponse RestServer::Impl::handleGraphSwitch(const HttpRequest& req) {
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
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 400);
    }
}

// POST /api/preflight
HttpResponse RestServer::Impl::handlePreflight(const HttpRequest& req) {
    try {
        const Json::Value body = parseJson(req.body);
        // Resolve requires
        Json::Value requires(Json::objectValue);
        if (body.isMember("requires") && body["requires"].isObject()) {
            requires = body["requires"];
        } else if (body.isMember("graph_id") && body["graph_id"].isString()) {
            const std::string gid = body["graph_id"].asString();
            auto dirs = graphDirCandidates();
            std::error_code ec;
            for (const auto& dir : dirs) {
                auto p1 = dir / (gid + ".yaml");
                auto p2 = dir / (gid + ".yml");
                if (std::filesystem::exists(p1, ec)) {
                    if (auto r = loadRequiresFromYaml((std::filesystem::weakly_canonical(p1, ec)).string())) { requires = *r; break; }
                } else if (std::filesystem::exists(p2, ec)) {
                    if (auto r = loadRequiresFromYaml((std::filesystem::weakly_canonical(p2, ec)).string())) { requires = *r; break; }
                }
            }
        }
        // Source caps
        Json::Value caps(Json::objectValue);
        if (body.isMember("source_caps") && body["source_caps"].isObject()) {
            caps = body["source_caps"];
        } else if (body.isMember("source") && body["source"].isObject()) {
            const auto& s = body["source"]; caps = s.isMember("caps") && s["caps"].isObject() ? s["caps"] : s;
        }
        // Caps 可缺省：若无能力信息则无法校验，返回 ok=true（降级）

        // Validate
        std::vector<std::string> reasons;
        auto get_vec2i = [](const Json::Value& v) -> std::pair<int,int> {
            if (v.isArray() && v.size()>=2) return { v[0].asInt(), v[1].asInt() };
            return {0,0};
        };
        auto in_str_list = [](const Json::Value& arr, const std::string& s) { if(!arr.isArray() || !arr.size()) return true; for(const auto& x: arr) { if(x.isString() && x.asString()==s) return true; } return false; };

        // pixel format
        std::string pix = caps.isMember("pix_fmt") ? caps["pix_fmt"].asString() : (caps.isMember("pixel_format")? caps["pixel_format"].asString() : "");
        if (!caps.isNull() && caps.isObject() && !pix.empty() && requires.isMember("color_format") && !in_str_list(requires["color_format"], pix)) {
            reasons.push_back(std::string("像素格式不匹配: ") + pix);
        }
        // resolution
        auto res = (caps.isObject() && caps.isMember("resolution")) ? get_vec2i(caps["resolution"]) : std::make_pair(0,0);
        auto maxr = requires.isMember("max_resolution") ? get_vec2i(requires["max_resolution"]) : std::make_pair(99999,99999);
        auto minr = requires.isMember("min_resolution") ? get_vec2i(requires["min_resolution"]) : std::make_pair(0,0);
        if ((res.first>0 && res.second>0)) {
            if (res.first > maxr.first || res.second > maxr.second) {
                reasons.push_back("分辨率超过上限: " + std::to_string(res.first) + "x" + std::to_string(res.second) + " > " + std::to_string(maxr.first) + "x" + std::to_string(maxr.second));
            }
            if (res.first < minr.first || res.second < minr.second) {
                reasons.push_back("分辨率低于下限: " + std::to_string(res.first) + "x" + std::to_string(res.second) + " < " + std::to_string(minr.first) + "x" + std::to_string(minr.second));
            }
        }
        // fps
        int fps = (caps.isObject() && caps.isMember("fps")) ? caps["fps"].asInt() : ((caps.isObject() && caps.isMember("frame_rate"))? caps["frame_rate"].asInt() : 0);
        auto fr = requires.isMember("fps_range") ? get_vec2i(requires["fps_range"]) : std::make_pair(0, 1000);
        if (fps>0 && (fps < fr.first || fps > fr.second)) {
            reasons.push_back("帧率不在范围 " + std::to_string(fr.first) + "-" + std::to_string(fr.second) + ": " + std::to_string(fps));
        }

        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        data["ok"] = reasons.empty();
        Json::Value arr(Json::arrayValue); for(const auto& r: reasons) arr.append(r); data["reasons"] = arr;
        if (!requires.isNull()) data["requires"] = requires;
        if (!caps.isNull()) data["caps"] = caps;
        payload["data"] = data;
        return jsonResponse(payload, 200);
    } catch (const std::exception& ex) {
        return errorResponse(ex.what(), 500);
    }
}

HttpResponse RestServer::Impl::handleSystemStats(const HttpRequest& /*req*/) {
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    const auto stats = app.systemStats();
    data["total_pipelines"] = static_cast<Json::UInt64>(stats.total_pipelines);
    data["running_pipelines"] = static_cast<Json::UInt64>(stats.running_pipelines);
    data["aggregate_fps"] = stats.aggregate_fps;
    data["processed_frames"] = static_cast<Json::UInt64>(stats.processed_frames);
    data["dropped_frames"] = static_cast<Json::UInt64>(stats.dropped_frames);
    data["transport_packets"] = static_cast<Json::UInt64>(stats.transport_packets);
    data["transport_bytes"] = static_cast<Json::UInt64>(stats.transport_bytes);
    // Aggregate zero-copy metrics across pipelines (sum of per-pipeline)
    {
        uint64_t d2d = 0, cpu_fb = 0, eagain = 0, ov_k = 0, ov_p = 0;
        for (const auto& info : app.pipelines()) {
            d2d   += info.zc.d2d_nv12_frames;
            cpu_fb+= info.zc.cpu_fallback_skips;
            eagain+= info.zc.eagain_retry_count;
            ov_k  += info.zc.overlay_nv12_kernel_hits;
            ov_p  += info.zc.overlay_nv12_passthrough;
        }
        Json::Value z(Json::objectValue);
        z["d2d_nv12_frames"] = static_cast<Json::UInt64>(d2d);
        z["cpu_fallback_skips"] = static_cast<Json::UInt64>(cpu_fb);
        z["eagain_retry_count"] = static_cast<Json::UInt64>(eagain);
        z["overlay_nv12_kernel_hits"] = static_cast<Json::UInt64>(ov_k);
        z["overlay_nv12_passthrough"] = static_cast<Json::UInt64>(ov_p);
        data["zerocopy_metrics"] = z;
    }
    payload["data"] = data;
    return jsonResponse(payload, 200);
}

} // namespace va::server
