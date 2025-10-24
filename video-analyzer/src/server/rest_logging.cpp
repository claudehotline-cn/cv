#include "server/rest_impl.hpp"
#include "server/sse_metrics.hpp"
#include <atomic>

namespace va::server {

va::core::LogLevel RestServer::Impl::parseLevelStr(const std::string& s) {
    std::string v = toLower(s);
    if (v == "trace") return va::core::LogLevel::Trace;
    if (v == "debug") return va::core::LogLevel::Debug;
    if (v == "warn" || v == "warning") return va::core::LogLevel::Warn;
    if (v == "error" || v == "err") return va::core::LogLevel::Error;
    return va::core::LogLevel::Info;
}

HttpResponse RestServer::Impl::handleLoggingGet(const HttpRequest& /*req*/) {
    auto& logger = va::core::Logger::instance();
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    auto lvlToStr = [](va::core::LogLevel l) { switch(l) {case va::core::LogLevel::Trace:return "trace";case va::core::LogLevel::Debug:return "debug";case va::core::LogLevel::Info:return "info";case va::core::LogLevel::Warn:return "warn";case va::core::LogLevel::Error:return "error";} return "info"; };
    data["level"] = lvlToStr(logger.level());
    data["format"] = (logger.format()==va::core::LogFormat::Json?"json":"text");
    Json::Value mods(Json::objectValue);
    for (auto& kv : logger.moduleLevels()) { mods[kv.first] = lvlToStr(kv.second); }
    data["modules"] = mods;
    data["file_path"] = logger.filePath();
    data["file_max_size_kb"] = logger.fileMaxSizeKB();
    data["file_max_files"] = logger.fileMaxFiles();
    payload["data"] = data;
    return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleLoggingSet(const HttpRequest& req) {
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
        // modules map
        if (body.isMember("modules") && body["modules"].isObject()) {
            const auto& m = body["modules"];
            for (const auto& name : m.getMemberNames()) {
                if (m[name].isString()) {
                    logger.setModuleLevel(name, parseLevelStr(m[name].asString()));
                }
            }
        }
        // module_levels (string or object), same语义
        if (body.isMember("module_levels")) {
            const auto& ml = body["module_levels"];
            if (ml.isObject()) {
                for (const auto& name : ml.getMemberNames()) {
                    if (ml[name].isString()) logger.setModuleLevel(name, parseLevelStr(ml[name].asString()));
                }
            } else if (ml.isString()) {
                // parse "comp:level,comp2:level"
                std::string s = ml.asString(); size_t start = 0;
                while (start < s.size()) {
                    size_t comma = s.find(',', start);
                    std::string pair = s.substr(start, comma == std::string::npos ? std::string::npos : comma - start);
                    size_t colon = pair.find(':');
                    if (colon != std::string::npos) {
                        std::string comp = pair.substr(0, colon);
                        std::string lvl = pair.substr(colon + 1);
                        auto trim = [](std::string& x) { x.erase(0, x.find_first_not_of(" \t")); x.erase(x.find_last_not_of(" \t") + 1); };
                        trim(comp); trim(lvl);
                        if (!comp.empty() && !lvl.empty()) logger.setModuleLevel(comp, parseLevelStr(lvl));
                    }
                    if (comma == std::string::npos) break; else start = comma + 1;
                }
            }
        }

        Json::Value ok = successPayload();
        ok["message"] = "logging updated";
        return jsonResponse(ok);
    } catch (const std::exception& ex) {
        return errorResponse(std::string("logging set failed: ") + ex.what(), 400);
    }
}

    // --- SSE helpers and streams ---
    void RestServer::Impl::sseSendAll(int fd, const std::string& s) {
#ifdef _WIN32
        send(fd, s.c_str(), static_cast<int>(s.size()), 0);
#else
        send(fd, s.c_str(), s.size(), 0);
#endif
    }

void RestServer::Impl::sseWriteHeaders(int fd) {
    std::ostringstream hs;
    hs << "HTTP/1.1 200 OK\r\n";
    hs << "Content-Type: text/event-stream\r\n";
    // CORS for EventSource (SSE)
    hs << "Access-Control-Allow-Origin: *\r\n";
    hs << "Access-Control-Allow-Methods: GET, OPTIONS\r\n";
    hs << "Access-Control-Allow-Headers: Content-Type,Authorization,Last-Event-ID,Cache-Control,X-Requested-With\r\n";
    hs << "Cache-Control: no-cache\r\n";
    hs << "Connection: keep-alive\r\n\r\n";
    sseSendAll(fd, hs.str());
}

void RestServer::Impl::sseEvent(int fd, const char* event, const Json::Value& data) {
    Json::StreamWriterBuilder b; std::string body = Json::writeString(b, data);
    std::ostringstream ss;
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

void RestServer::Impl::sseEventWithId(int fd, const char* event, const Json::Value& data, std::uint64_t id, int retry_ms) {
    Json::StreamWriterBuilder b; std::string body = Json::writeString(b, data);
    std::ostringstream ss;
    ss << "id: " << id << "\n";
    if (retry_ms > 0) ss << "retry: " << retry_ms << "\n";
    if (event && *event) { ss << "event: " << event << "\n"; }
    std::istringstream is(body);
    std::string line; ss << "data: "; bool first = true;
    while (std::getline(is, line)) {
        if (!first) ss << "\ndata: ";
        if (!line.empty() && line.back()=='\r') line.pop_back();
        ss << line; first = false;
    }
    ss << "\n\n";
    sseSendAll(fd, ss.str());
}

void RestServer::Impl::sseKeepAlive(int fd) {
    sseSendAll(fd, "\n");
}

void RestServer::Impl::streamLogsSSE(int fd, const HttpRequest& req) {
    // Active connections accounting
    struct Guard { ~Guard(){ g_sse_logs_active.fetch_sub(1, std::memory_order_relaxed); } } guard;
    g_sse_logs_active.fetch_add(1, std::memory_order_relaxed);
    // Reconnect signal
    try { auto it=req.headers.find("Last-Event-ID"); if (it!=req.headers.end()) g_sse_reconnects_total.fetch_add(1, std::memory_order_relaxed); } catch (...) {}
    sseWriteHeaders(fd);
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string("info");
    auto fingerprint = [&]() { std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()) { key+="#"; key+=level; } return std::hash<std::string>{}(key); };
    auto make_items = [&]() { Json::Value arr(Json::arrayValue); auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr))*1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id!=pipeline) continue; Json::Value e(Json::objectValue); e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level; e["type"] = level; e["msg"] = std::string("running bytes=") + std::to_string(info.transport_stats.bytes); arr.append(e);} return arr; };
    uint64_t last = 0; const int interval_ms = 500; const int keepalive_ms = 15000; uint64_t last_keep = 0; auto start = std::chrono::steady_clock::now();
    // initial
    { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(fingerprint()); d["items"] = make_items(); sseEvent(fd, "logs", d); last = d["rev"].asUInt64(); }
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto rev = fingerprint(); if (rev!=last) { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(rev); d["items"] = make_items(); sseEvent(fd, "logs", d); last=rev; last_keep=0; continue; }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count(); if (elapsed-last_keep>=keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
    }
}

void RestServer::Impl::streamEventsSSE(int fd, const HttpRequest& req) {
    struct Guard { ~Guard(){ g_sse_events_active.fetch_sub(1, std::memory_order_relaxed); } } guard;
    g_sse_events_active.fetch_add(1, std::memory_order_relaxed);
    try { auto it=req.headers.find("Last-Event-ID"); if (it!=req.headers.end()) g_sse_reconnects_total.fetch_add(1, std::memory_order_relaxed); } catch (...) {}
    sseWriteHeaders(fd);
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string("info");
    auto fingerprint = [&]() { std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()) { key+="#"; key+=level; } return std::hash<std::string>{}(key); };
    auto make_items = [&]() { Json::Value arr(Json::arrayValue); auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr))*1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id!=pipeline) continue; Json::Value e(Json::objectValue); e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level; e["type"] = level; e["msg"] = std::string("pipeline running packets=") + std::to_string(info.transport_stats.packets); arr.append(e);} return arr; };
    uint64_t last = 0; const int interval_ms = 700; const int keepalive_ms = 15000; uint64_t last_keep = 0; auto start = std::chrono::steady_clock::now();
    { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(fingerprint()); d["items"] = make_items(); sseEvent(fd, "events", d); last = d["rev"].asUInt64(); }
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto rev = fingerprint(); if (rev!=last) { Json::Value d(Json::objectValue); d["rev"] = static_cast<Json::UInt64>(rev); d["items"] = make_items(); sseEvent(fd, "events", d); last=rev; last_keep=0; continue; }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count(); if (elapsed-last_keep>=keepalive_ms) { sseKeepAlive(fd); last_keep = static_cast<uint64_t>(elapsed); }
    }
}

// --- Observability: logs (DB only; no fallback) ---
HttpResponse RestServer::Impl::handleLogsRecent(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string();
    std::string stream_id = q.count("stream_id") ? q["stream_id"] : std::string();
    std::string node = q.count("node") ? q["node"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    const uint64_t from_ts = get_uint64("from_ts", 0);
    const uint64_t to_ts   = get_uint64("to_ts", 0);
    int page = 1; if (auto it=q.find("page"); it!=q.end()) { try { page = std::stoi(it->second); } catch(...) {} }
    int page_size = 0; if (auto it=q.find("page_size"); it!=q.end()) { try { page_size = std::stoi(it->second); } catch(...) {} }
    if (page_size <= 0) {
        int legacy_limit = 0; if (auto it=q.find("limit"); it!=q.end()) { try { legacy_limit = std::stoi(it->second); } catch(...) {} }
        page_size = (legacy_limit > 0 ? legacy_limit : 200);
    }
    if (!logs_repo) {
        return errorResponse("database disabled", 503);
    }
    std::vector<va::storage::LogRow> rows; std::string err; std::int64_t total = 0;
    if (!logs_repo->listRecentFilteredPaged(pipeline, level, stream_id, node, from_ts, to_ts, page, page_size, &rows, &total, &err)) {
        return errorResponse(err.empty()? std::string("db query failed") : err, 503);
    }
    Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
    for (const auto& r : rows) {
        Json::Value row(Json::objectValue);
        row["ts"] = static_cast<Json::UInt64>(r.ts_ms);
        row["level"] = r.level; if(!r.pipeline.empty()) row["pipeline"] = r.pipeline; if(!r.node.empty()) row["node"] = r.node; if(!r.stream_id.empty()) row["stream_id"] = r.stream_id; row["msg"] = r.message;
        if(!r.extra_json.empty()) { Json::Value ej; try{ Json::CharReaderBuilder b; std::string errs; std::istringstream is(r.extra_json); Json::parseFromStream(b, is, &ej, &errs); }catch(...) { ej = Json::Value(Json::nullValue);} row["extra"] = ej; }
        arr.append(row);
    }
    data["items"] = arr; data["total"] = static_cast<Json::UInt64>(total); data["page"] = page; data["page_size"] = page_size; payload["data"] = data; return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleLogsWatch(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
    auto fingerprint = [&]() { std::string key; key.reserve(128); for (const auto& p : app.pipelines()) { if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ':'; key += (p.running? '1':'0'); key += ';'; } if(!level.empty()) { key+="#"; key+=level; } return std::hash<std::string>{}(key); };
    const uint64_t since = get_uint64("since", 0);
    int tmp_to = get_int("timeout_ms", 12000); if (tmp_to < 100) tmp_to = 100; const int timeout_ms = tmp_to;
    int tmp_iv = get_int("interval_ms", 300);  if (tmp_iv < 80)  tmp_iv = 80;  const int interval_ms = tmp_iv;
    auto rev_now = fingerprint();
    if (!since || since != rev_now) {
        Json::Value payload = successPayload(); Json::Value data(Json::objectValue);
        data["rev"] = static_cast<Json::UInt64>(rev_now);
        Json::Value items(Json::arrayValue);
        auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL);
        for (const auto& info : app.pipelines()) {
            if (!info.running) continue; if (!pipeline.empty() && info.profile_id != pipeline) continue;
            Json::Value row(Json::objectValue);
            row["ts"] = now_ms; row["level"] = level.empty()? "Info" : level; row["pipeline"] = info.profile_id; row["node"] = "pipeline"; row["msg"] = std::string("running fps=") + std::to_string(info.metrics.fps);
            items.append(row);
        }
        data["items"] = items; payload["data"] = data; return jsonResponse(payload, 200);
    }
    auto start = std::chrono::steady_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto cur = fingerprint();
        if (cur != since) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(cur); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
        if (elapsed >= timeout_ms) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(since); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
    }
}

// --- Observability: events (DB only; no fallback) ---
HttpResponse RestServer::Impl::handleEventsRecent(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string();
    std::string stream_id = q.count("stream_id") ? q["stream_id"] : std::string();
    std::string node = q.count("node") ? q["node"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    const uint64_t from_ts = get_uint64("from_ts", 0);
    const uint64_t to_ts   = get_uint64("to_ts", 0);
    int page = 1; if (auto it=q.find("page"); it!=q.end()) { try { page = std::stoi(it->second); } catch(...) {} }
    int page_size = 0; if (auto it=q.find("page_size"); it!=q.end()) { try { page_size = std::stoi(it->second); } catch(...) {} }
    if (page_size <= 0) {
        int legacy_limit = 0; if (auto it=q.find("limit"); it!=q.end()) { try { legacy_limit = std::stoi(it->second); } catch(...) {} }
        page_size = (legacy_limit > 0 ? legacy_limit : 50);
    }
    if (!events_repo) {
        return errorResponse("database disabled", 503);
    }
    std::vector<va::storage::EventRow> rows; std::string err; std::int64_t total = 0;
    if (!events_repo->listRecentFilteredPaged(pipeline, level, stream_id, node, from_ts, to_ts, page, page_size, &rows, &total, &err)) {
        return errorResponse(err.empty()? std::string("db query failed") : err, 503);
    }
    Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
    for (const auto& r : rows) {
        Json::Value e(Json::objectValue);
        e["ts"] = static_cast<Json::UInt64>(r.ts_ms);
        e["level"] = r.level; e["type"] = r.type; if(!r.pipeline.empty()) e["pipeline"] = r.pipeline; if(!r.node.empty()) e["node"] = r.node; if(!r.stream_id.empty()) e["stream_id"] = r.stream_id; e["msg"] = r.msg; if(!r.extra_json.empty()) { Json::Value ej; try{ Json::CharReaderBuilder b; std::string errs; std::istringstream is(r.extra_json); Json::parseFromStream(b, is, &ej, &errs); }catch(...) { ej = Json::Value(Json::nullValue);} e["extra"] = ej; }
        arr.append(e);
    }
    data["items"] = arr; data["total"] = static_cast<Json::UInt64>(total); data["page"] = page; data["page_size"] = page_size; payload["data"] = data; return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleEventsWatch(const HttpRequest& req) {
    auto q = parseQueryKV(req.query);
    std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
    std::string level = q.count("level") ? q["level"] : std::string();
    auto get_uint64 = [&](const char* k, uint64_t def) { auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
    auto get_int = [&](const char* k, int def) { auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
    auto fingerprint = [&]() { std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()) { key+="#"; key+=level; } return std::hash<std::string>{}(key); };
    const uint64_t since = get_uint64("since", 0);
    int timeout_ms = get_int("timeout_ms", 12000); if (timeout_ms < 100) timeout_ms = 100;
    int interval_ms = get_int("interval_ms", 300); if (interval_ms < 80) interval_ms = 80;
    auto rev_now = fingerprint();
    if (!since || since != rev_now) {
        Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev_now);
        data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200);
    }
    auto start = std::chrono::steady_clock::now();
    while (true) {
        std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto cur = fingerprint();
        if (cur != since) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(cur); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
        auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
        if (elapsed >= timeout_ms) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(since); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
    }
}

} // namespace va::server
namespace va::server {
// Define SSE metrics counters
std::atomic<int> g_sse_subscriptions_active{0};
std::atomic<int> g_sse_sources_active{0};
std::atomic<int> g_sse_logs_active{0};
std::atomic<int> g_sse_events_active{0};
std::atomic<unsigned long long> g_sse_reconnects_total{0ULL};
}
