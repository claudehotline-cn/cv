
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

      HttpResponse handleSources(const HttpRequest& /*req*/) {
          Json::Value payload = successPayload();
          Json::Value data(Json::arrayValue);
          // Aggregate by stream_id
          struct Agg { std::string id; std::string uri; bool running{false}; double fps{0.0}; };
          std::unordered_map<std::string, Agg> by_id;
          for (const auto& info : app.pipelines()) {
              auto it = by_id.find(info.stream_id);
              if (it == by_id.end()) {
                  Agg a; a.id = info.stream_id; a.uri = info.source_uri; a.running = info.running; a.fps = info.metrics.fps; by_id.emplace(info.stream_id, a);
              } else {
                  it->second.running = it->second.running || info.running;
                  if (info.metrics.fps > it->second.fps) it->second.fps = info.metrics.fps;
                  if (it->second.uri.empty()) it->second.uri = info.source_uri;
              }
          }
          // Enrich from VSM if available (list and per-source describe)
          std::unordered_map<std::string, Json::Value> vsm_list_map;
          // Fallback map by normalized URI to tolerate id mismatches between CP pipeline id and VSM attach id
          std::unordered_map<std::string, Json::Value> vsm_list_by_uri;
          auto normalize_uri = [](std::string u){
              // very lightweight normalization: trim spaces and lower-case
              u.erase(u.begin(), std::find_if(u.begin(), u.end(), [](unsigned char ch){ return !std::isspace(ch); }));
              u.erase(std::find_if(u.rbegin(), u.rend(), [](unsigned char ch){ return !std::isspace(ch); }).base(), u.end());
              std::transform(u.begin(), u.end(), u.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
              return u;
          };
          if (auto snap = vsm_sources_snapshot(600); snap && snap->isArray()) {
              for (const auto& s : *snap) {
                  std::string id = s.isMember("id")? s["id"].asString() : (s.isMember("attach_id")? s["attach_id"].asString() : "");
                  if (id.empty()) continue; vsm_list_map[id] = s;
                  auto& a = by_id[id]; if (a.id.empty()) a.id = id;
                  if (a.uri.empty() && s.isMember("uri")) a.uri = s["uri"].asString();
                  if (s.isMember("uri") && s["uri"].isString()) {
                      vsm_list_by_uri[normalize_uri(s["uri"].asString())] = s;
                  }
                  std::string phase = s.isMember("phase")? s["phase"].asString() : std::string();
                  if (!phase.empty()) {
                      std::string p = toLower(phase);
                      if (p.find("ready")!=std::string::npos || p.find("run")!=std::string::npos) a.running = true;
                      if (p.find("stop")!=std::string::npos) a.running = false;
                  }
                  if (s.isMember("fps") && s["fps"].isNumeric()) {
                      double vf = s["fps"].asDouble(); if (vf > a.fps) a.fps = vf;
                  }
              }
          }
          for (auto& kv : by_id) {
              const auto& a = kv.second;
              Json::Value node(Json::objectValue);
              node["id"] = a.id;
              node["name"] = a.id;
              node["uri"] = a.uri;
              node["status"] = a.running ? "Running" : "Stopped";
              node["fps"] = a.fps;
              // Optional: merge VSM per-source metrics (jitter/rtt/loss) and phase/profile
              if (auto it = vsm_list_map.find(a.id); it != vsm_list_map.end()) {
                  const auto& s = it->second;
                  if (s.isMember("profile")) node["profile"] = s["profile"];
                  if (s.isMember("phase"))   node["phase"] = s["phase"];
                  // Prefer lightweight caps from VSM list to avoid per-source describe when possible
                  if (s.isMember("caps"))    node["caps"] = s["caps"];
              } else if (!a.uri.empty()) {
                  // Fallback by URI when ids differ (e.g., CP uses stream_id while VSM uses attach_id)
                  auto it2 = vsm_list_by_uri.find(normalize_uri(a.uri));
                  if (it2 != vsm_list_by_uri.end()) {
                      const auto& s = it2->second;
                      if (s.isMember("profile")) node["profile"] = s["profile"];
                      if (s.isMember("phase"))   node["phase"] = s["phase"];
                      if (s.isMember("caps"))    node["caps"] = s["caps"];
                  }
              }
              // Enrich with detailed metrics from VSM describe (only if needed or available)
              if (auto desc = vsm_source_describe(a.id, 400); desc && desc->isObject()) {
                  const auto& d = *desc;
                  if (d.isMember("jitter_ms")) node["jitter_ms"] = d["jitter_ms"];
                  if (d.isMember("rtt_ms"))    node["rtt_ms"] = d["rtt_ms"];
                  if (d.isMember("loss_ratio"))node["loss_ratio"] = d["loss_ratio"];
                  if (d.isMember("phase"))     node["phase"] = d["phase"];
                  if (!node.isMember("caps") && d.isMember("caps")) node["caps"] = d["caps"];
              }
              // caps: not provided by VSM currently; leave absent to be determined by future extension
              data.append(node);
          }
          payload["data"] = data;
          return jsonResponse(payload, 200);
      }

      HttpResponse handleSourcesWatch(const HttpRequest& req) {
          // Long-poll style: if since==current rev, wait up to timeout_ms for change; else return immediately
          auto q = parseQueryKV(req.query);
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try{ return static_cast<uint64_t>(std::stoull(it->second)); }catch(...){ return def; } };
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...){ return def; } };

          auto snapshot = [&]() {
              // Reuse aggregation
              struct Agg { std::string id; std::string uri; bool running{false}; double fps{0.0}; };
              std::unordered_map<std::string, Agg> by_id;
              for (const auto& info : app.pipelines()) {
                  auto it = by_id.find(info.stream_id);
                  if (it == by_id.end()) {
                      Agg a; a.id = info.stream_id; a.uri = info.source_uri; a.running = info.running; a.fps = info.metrics.fps; by_id.emplace(info.stream_id, a);
                  } else {
                      it->second.running = it->second.running || info.running;
                      if (info.metrics.fps > it->second.fps) it->second.fps = info.metrics.fps;
                      if (it->second.uri.empty()) it->second.uri = info.source_uri;
                  }
              }
              // compute fingerprint
              std::string concat;
              concat.reserve(by_id.size()*32);
              for (auto& kv : by_id) {
