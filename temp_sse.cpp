        if (event && *event) { ss << "event: " << event << "\n"; }
        // split body by lines to avoid CRLF issues
        std::istringstream is(body);
        std::string line; ss << "data: ";
        bool first = true;
        while (std::getline(is, line)) {
            if (!first) ss << "\ndata: ";
            if (!line.empty() && line.back()=='\r') line.pop_back();
            ss << line; first = false;
        }
        ss << "\n\n";
        sseSendAll(fd, ss.str());
    }
    static void sseKeepAlive(int fd) {
        sseSendAll(fd, "\n");
    }

    void streamSourcesSSE(int fd, const HttpRequest& req) {
        sseWriteHeaders(fd);
        auto q = parseQueryKV(req.query);
        auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try{ return static_cast<uint64_t>(std::stoull(it->second)); }catch(...){ return def; } };
        auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try{ return std::stoi(it->second); }catch(...){ return def; } };
        const int interval_ms = (std::max)(80, get_int("interval_ms", 300));
        const int keepalive_ms = (std::max)(1000, get_int("keepalive_ms", 15000));

        auto make_snapshot = [&]() {
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
            // Merge VSM lightweight list
            if (auto snap = vsm_sources_snapshot(600); snap && snap->isArray()) {
                for (const auto& s : *snap) {
                    std::string id = s.isMember("id")? s["id"].asString() : (s.isMember("attach_id")? s["attach_id"].asString() : "");
                    if (id.empty()) continue; auto& a = by_id[id]; if (a.id.empty()) a.id = id; if (a.uri.empty() && s.isMember("uri")) a.uri = s["uri"].asString();
                }
            }
            Json::Value items(Json::arrayValue);
            for (auto& kv : by_id) {
                const auto& a = kv.second; Json::Value n(Json::objectValue);
                n["id"] = a.id; n["name"] = a.id; n["uri"] = a.uri; n["status"] = a.running?"Running":"Stopped"; n["fps"] = a.fps;
                items.append(n);
            }
            return items;
        };
        auto fingerprint = [&]() {
            std::string key; key.reserve(64);
            for (const auto& p : app.pipelines()) { key += p.stream_id; key += p.running? '1':'0'; key += ';'; }
            return std::hash<std::string>{}(key);
        };

        uint64_t last_rev = 0; uint64_t last_keep = 0;
        // Initial burst
        {
            Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(fingerprint()); data["items"] = make_snapshot();
            sseEvent(fd, "sources", data); last_rev = data["rev"].asUInt64();
        }
        auto start = std::chrono::steady_clock::now();
        while (true) {
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
            auto rev = fingerprint();
            if (rev != last_rev) {
                Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev); data["items"] = make_snapshot(); sseEvent(fd, "sources", data); last_rev = rev; last_keep = 0; continue;
            }
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
            if (elapsed - last_keep >= keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
        }
    }

    void streamLogsSSE(int fd, const HttpRequest& req) {
        sseWriteHeaders(fd);
        auto q = parseQueryKV(req.query);
        std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
        std::string level = q.count("level") ? q["level"] : std::string("info");
        auto fingerprint = [&](){ std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()){ key+="#"; key+=level; } return std::hash<std::string>{}(key); };
        auto make_items = [&](){ Json::Value arr(Json::arrayValue); auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr))*1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id!=pipeline) continue; Json::Value e(Json::objectValue); e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level; e["type"] = level; e["msg"] = std::string("running bytes=") + std::to_string(info.transport_stats.bytes); arr.append(e);} return arr; };
        uint64_t last = 0; const int interval_ms = 500; const int keepalive_ms = 15000; uint64_t last_keep = 0; auto start = std::chrono::steady_clock::now();
        // initial
        { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(fingerprint()); d["items"] = make_items(); sseEvent(fd, "logs", d); last = d["rev"].asUInt64(); }
        while (true) {
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto rev = fingerprint(); if (rev!=last) { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(rev); d["items"] = make_items(); sseEvent(fd, "logs", d); last=rev; last_keep=0; continue; }
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count(); if (elapsed-last_keep>=keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
        }
    }

    void streamEventsSSE(int fd, const HttpRequest& req) {
        sseWriteHeaders(fd);
        auto q = parseQueryKV(req.query);
        std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
        std::string level = q.count("level") ? q["level"] : std::string("info");
        auto fingerprint = [&](){ std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()){ key+="#"; key+=level; } return std::hash<std::string>{}(key); };
        auto make_items = [&](){ Json::Value arr(Json::arrayValue); auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr))*1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id!=pipeline) continue; Json::Value e(Json::objectValue); e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level; e["type"] = level; e["msg"] = std::string("pipeline running packets=") + std::to_string(info.transport_stats.packets); arr.append(e);} return arr; };
        uint64_t last = 0; const int interval_ms = 700; const int keepalive_ms = 15000; uint64_t last_keep = 0; auto start = std::chrono::steady_clock::now();
        { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(fingerprint()); d["items"] = make_items(); sseEvent(fd, "events", d); last = d["rev"].asUInt64(); }
        while (true) {
            std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto rev = fingerprint(); if (rev!=last) { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(rev); d["items"] = make_items(); sseEvent(fd, "events", d); last=rev; last_keep=0; continue; }
            auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count(); if (elapsed-last_keep>=keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
        }
    }
    HttpResponse handleLoggingSet(const HttpRequest& req) {
        try {
            const Json::Value body = parseJson(req.body);
            auto& logger = va::core::Logger::instance();

            // level
            if (body.isMember("level") && body["level"].isString()) {
                logger.setLevel(parseLevelStr(body["level"].asString()));
            }
            // format
            if (body.isMember("format") && body["format"].isString()) {
                std::string f = toLower(body["format"].asString());
                logger.setFormat(f == "json" ? va::core::LogFormat::Json : va::core::LogFormat::Text);
            }
