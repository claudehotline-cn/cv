#include "server/rest.hpp"

#include "app/application.hpp"
#include "analyzer/analyzer.hpp"
#include "core/engine_manager.hpp"
#include "core/logger.hpp"
#include "core/global_metrics.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"
#include "core/nvdec_events.hpp"

#include <json/json.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstddef>
#include <initializer_list>
#include <map>
#include <mutex>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
#undef DELETE
#else
#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace va::server {

namespace {

struct HttpRequest {
    std::string method;
    std::string path;
    std::string query;
    std::map<std::string, std::string> headers;
    std::string body;
    std::map<std::string, std::string> params;
};

struct HttpResponse {
    int status_code {200};
    std::map<std::string, std::string> headers {
        {"Content-Type", "application/json"},
        {"Access-Control-Allow-Origin", "*"},
        {"Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS,PATCH"},
        {"Access-Control-Allow-Headers", "Content-Type,Authorization"}
    };
    std::string body;
};

Json::Value parseJson(const std::string& body) {
    if (body.empty()) {
        return Json::Value(Json::objectValue);
    }
    Json::CharReaderBuilder builder;
    std::string errs;
    std::istringstream iss(body);
    Json::Value root;
    if (!Json::parseFromStream(builder, iss, &root, &errs)) {
        throw std::runtime_error("JSON parse error: " + errs);
    }
    return root;
}

std::string toLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

std::optional<std::string> getStringField(const Json::Value& node, std::initializer_list<const char*> keys) {
    for (const auto* key : keys) {
        if (node.isMember(key) && node[key].isString()) {
            return node[key].asString();
        }
    }
    return std::nullopt;
}

Json::Value modelToJson(const DetectionModelEntry& model) {
    Json::Value node(Json::objectValue);
    node["id"] = model.id;
    node["task"] = model.task;
    node["family"] = model.family;
    node["variant"] = model.variant;
    node["type"] = model.type;
    node["path"] = model.path;
    node["input_width"] = model.input_width;
    node["input_height"] = model.input_height;
    node["confidence_threshold"] = model.conf;
    node["iou_threshold"] = model.iou;
    return node;
}

Json::Value encoderConfigToJson(const va::core::EncoderConfig& cfg) {
    Json::Value node(Json::objectValue);
    node["width"] = cfg.width;
    node["height"] = cfg.height;
    node["fps"] = cfg.fps;
    node["bitrate_kbps"] = cfg.bitrate_kbps;
    node["gop"] = cfg.gop;
    node["bframes"] = cfg.bframes;
    node["zero_latency"] = cfg.zero_latency;
    node["preset"] = cfg.preset;
    node["tune"] = cfg.tune;
    node["profile"] = cfg.profile;
    node["codec"] = cfg.codec;
    return node;
}

Json::Value profileToJson(const ProfileEntry& profile) {
    Json::Value node(Json::objectValue);
    node["name"] = profile.name;
    node["task"] = profile.task;
    node["model_id"] = profile.model_id;
    node["model_family"] = profile.model_family;
    node["model_variant"] = profile.model_variant;
    node["model_path"] = profile.model_path;
    node["input_width"] = profile.input_width;
    node["input_height"] = profile.input_height;
    va::core::EncoderConfig enc_cfg;
    enc_cfg.width = profile.enc_width;
    enc_cfg.height = profile.enc_height;
    enc_cfg.fps = profile.enc_fps;
    enc_cfg.bitrate_kbps = profile.enc_bitrate_kbps;
    enc_cfg.gop = profile.enc_gop;
    enc_cfg.zero_latency = profile.enc_zero_latency;
    enc_cfg.bframes = profile.enc_bframes;
    enc_cfg.preset = profile.enc_preset;
    enc_cfg.tune = profile.enc_tune;
    enc_cfg.profile = profile.enc_profile;
    enc_cfg.codec = profile.enc_codec;
    node["encoder"] = encoderConfigToJson(enc_cfg);
    node["publish_whip_template"] = profile.publish_whip_template;
    node["publish_whep_template"] = profile.publish_whep_template;
    return node;
}

Json::Value metricsToJson(const va::core::Pipeline::Metrics& metrics) {
    Json::Value node(Json::objectValue);
    node["fps"] = metrics.fps;
    node["avg_latency_ms"] = metrics.avg_latency_ms;
    node["last_processed_ms"] = metrics.last_processed_ms;
    node["processed_frames"] = static_cast<Json::UInt64>(metrics.processed_frames);
    node["dropped_frames"] = static_cast<Json::UInt64>(metrics.dropped_frames);
    return node;
}

Json::Value transportStatsToJson(const va::media::ITransport::Stats& stats) {
    Json::Value node(Json::objectValue);
    node["connected"] = stats.connected;
    node["packets"] = static_cast<Json::UInt64>(stats.packets);
    node["bytes"] = static_cast<Json::UInt64>(stats.bytes);
    return node;
}

class SimpleHttpServer {
public:
    using Handler = std::function<HttpResponse(const HttpRequest&)>;

    explicit SimpleHttpServer(const RestServerOptions& options)
        : options_(options) {
#ifdef _WIN32
        WSADATA wsaData;
        WSAStartup(MAKEWORD(2, 2), &wsaData);
#endif
    }

    ~SimpleHttpServer() {
        stop();
#ifdef _WIN32
        WSACleanup();
#endif
    }

    void addRoute(const std::string& method, const std::string& pattern, Handler handler) {
        std::lock_guard<std::mutex> lock(routes_mutex_);
        routes_.push_back(Route{method, pattern, buildRegex(pattern), extractParams(pattern), std::move(handler)});
    }

    bool start() {
        if (running_.exchange(true)) {
            return false;
        }
        server_thread_ = std::thread(&SimpleHttpServer::serverLoop, this);
        return true;
    }

    void stop() {
        if (!running_.exchange(false)) {
            return;
        }

        if (server_socket_ != -1) {
#ifdef _WIN32
            shutdown(server_socket_, SD_BOTH);
            closesocket(server_socket_);
#else
            shutdown(server_socket_, SHUT_RDWR);
            close(server_socket_);
#endif
            server_socket_ = -1;
        }

        if (server_thread_.joinable()) {
            server_thread_.join();
        }
    }

private:
    struct Route {
        std::string method;
        std::string pattern;
        std::regex regex;
        std::vector<std::string> params;
        Handler handler;
    };

    RestServerOptions options_;
    std::atomic<bool> running_ {false};
    std::thread server_thread_;
    std::mutex routes_mutex_;
    std::vector<Route> routes_;
    int server_socket_ {-1};

    static std::regex buildRegex(const std::string& pattern) {
        std::string regex_pattern = std::regex_replace(pattern, std::regex(R"(:([a-zA-Z_][a-zA-Z0-9_]*))"), "([^/]+)");
        return std::regex("^" + regex_pattern + "$", std::regex::ECMAScript);
    }

    static std::vector<std::string> extractParams(const std::string& pattern) {
        std::vector<std::string> params;
        std::regex param_regex(R"(:([a-zA-Z_][a-zA-Z0-9_]*))");
        std::sregex_iterator iter(pattern.begin(), pattern.end(), param_regex);
        std::sregex_iterator end;
        for (; iter != end; ++iter) {
            params.push_back(iter->str(1));
        }
        return params;
    }

    void serverLoop() {
        server_socket_ = static_cast<int>(socket(AF_INET, SOCK_STREAM, 0));
        if (server_socket_ < 0) {
            VA_LOG_C(::va::core::LogLevel::Error, "rest") << "failed to create socket";
            running_ = false;
            return;
        }

        int opt = 1;
        setsockopt(server_socket_, SOL_SOCKET, SO_REUSEADDR, reinterpret_cast<const char*>(&opt), sizeof(opt));

        sockaddr_in addr{};
        addr.sin_family = AF_INET;
        addr.sin_port = htons(static_cast<uint16_t>(options_.port));

        if (options_.host == "0.0.0.0" || options_.host == "*") {
            addr.sin_addr.s_addr = INADDR_ANY;
        } else {
            if (inet_pton(AF_INET, options_.host.c_str(), &addr.sin_addr) <= 0) {
                VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "invalid host " << options_.host << ", defaulting to INADDR_ANY";
                addr.sin_addr.s_addr = INADDR_ANY;
            }
        }

        if (bind(server_socket_, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) {
            VA_LOG_C(::va::core::LogLevel::Error, "rest") << "bind failed on port " << options_.port;
            running_ = false;
#ifdef _WIN32
            closesocket(server_socket_);
#else
            close(server_socket_);
#endif
            server_socket_ = -1;
            return;
        }

        if (listen(server_socket_, 16) < 0) {
            VA_LOG_C(::va::core::LogLevel::Error, "rest") << "listen failed";
            running_ = false;
#ifdef _WIN32
            closesocket(server_socket_);
#else
            close(server_socket_);
#endif
            server_socket_ = -1;
            return;
        }

        VA_LOG_C(::va::core::LogLevel::Info, "rest") << "listening on " << options_.host << ":" << options_.port;

        while (running_) {
            sockaddr_in client_addr{};
            socklen_t client_len = sizeof(client_addr);
            int client_socket = accept(server_socket_, reinterpret_cast<sockaddr*>(&client_addr), &client_len);
            if (client_socket < 0) {
                if (running_) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "rest", 2000) << "accept failed";
                }
                continue;
            }

            std::thread(&SimpleHttpServer::handleClient, this, client_socket).detach();
        }
    }

    void handleClient(int client_socket) {
        constexpr size_t buffer_size = 8192;
        std::string request_data;
        request_data.reserve(buffer_size);
        char buffer[buffer_size];
        int received = 0;

        do {
#ifdef _WIN32
            received = recv(client_socket, buffer, static_cast<int>(buffer_size), 0);
#else
            received = static_cast<int>(recv(client_socket, buffer, buffer_size, 0));
#endif
            if (received > 0) {
                request_data.append(buffer, static_cast<size_t>(received));
                if (request_data.find("\r\n\r\n") != std::string::npos) {
                    break;
                }
            }
        } while (received > 0);

        if (request_data.empty()) {
#ifdef _WIN32
            closesocket(client_socket);
#else
            close(client_socket);
#endif
            return;
        }

        HttpRequest request;
        try {
            request = parseRequest(request_data);
        } catch (const std::exception& ex) {
            HttpResponse response;
            response.status_code = 400;
            Json::Value error(Json::objectValue);
            error["success"] = false;
            error["message"] = ex.what();
            response.body = Json::writeString(Json::StreamWriterBuilder{}, error);
            const auto raw = buildResponse(response);
            sendAll(client_socket, raw);
#ifdef _WIN32
            closesocket(client_socket);
#else
            close(client_socket);
#endif
            return;
        }

        if (request.method == "OPTIONS") {
            HttpResponse response;
            response.status_code = 204;
            const auto raw = buildResponse(response);
            sendAll(client_socket, raw);
#ifdef _WIN32
            closesocket(client_socket);
#else
            close(client_socket);
#endif
            return;
        }

        size_t content_length = 0;
        bool has_content_length = false;
        for (const auto& entry : request.headers) {
            std::string header_name = toLower(entry.first);
            if (header_name == "content-length") {
                try {
                    content_length = static_cast<size_t>(std::stoll(entry.second));
                    has_content_length = true;
                } catch (...) {
                    content_length = 0;
                }
                break;
            }
        }

        if (has_content_length && request.body.size() < content_length) {
            size_t remaining = content_length - request.body.size();
            while (remaining > 0) {
                const size_t chunk_size = (std::min)(remaining, static_cast<size_t>(buffer_size));
#ifdef _WIN32
                int read_bytes = recv(client_socket, buffer, static_cast<int>(chunk_size), 0);
#else
                int read_bytes = static_cast<int>(recv(client_socket, buffer, chunk_size, 0));
#endif
                if (read_bytes <= 0) {
                    break;
                }
                request.body.append(buffer, static_cast<size_t>(read_bytes));
                remaining -= static_cast<size_t>(read_bytes);
            }
        }

        HttpResponse response;
        bool matched = false;
        {
            std::lock_guard<std::mutex> lock(routes_mutex_);
            for (auto& route : routes_) {
                std::map<std::string, std::string> params;
                if (matchRoute(request.method, request.path, route, params)) {
                    request.params = std::move(params);
                    try {
                        response = route.handler(request);
                    } catch (const std::exception& ex) {
                        Json::Value error;
                        error["success"] = false;
                        error["message"] = ex.what();
                        response.status_code = 500;
                        response.body = Json::writeString(Json::StreamWriterBuilder{}, error);
                    }
                    matched = true;
                    break;
                }
            }
        }

        if (!matched) {
            Json::Value error;
            error["success"] = false;
            error["message"] = "Route not found";
            response.status_code = 404;
            response.body = Json::writeString(Json::StreamWriterBuilder{}, error);
        }

        const auto raw = buildResponse(response);
        sendAll(client_socket, raw);

#ifdef _WIN32
        closesocket(client_socket);
#else
        close(client_socket);
#endif
    }

    void sendAll(int client_socket, const std::string& data) const {
#ifdef _WIN32
        send(client_socket, data.data(), static_cast<int>(data.size()), 0);
#else
        send(client_socket, data.data(), data.size(), 0);
#endif
    }

    HttpRequest parseRequest(const std::string& raw_request) const {
        std::istringstream iss(raw_request);
        std::string line;
        HttpRequest request;

        if (!std::getline(iss, line)) {
            throw std::runtime_error("Invalid HTTP request");
        }

        if (!line.empty() && line.back() == '\r') {
            line.pop_back();
        }

        std::istringstream request_line(line);
        request_line >> request.method;
        std::string uri;
        request_line >> uri;

        auto query_pos = uri.find('?');
        if (query_pos != std::string::npos) {
            request.path = uri.substr(0, query_pos);
            request.query = uri.substr(query_pos + 1);
        } else {
            request.path = uri;
        }

        while (std::getline(iss, line) && line != "\r") {
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            auto colon = line.find(':');
            if (colon != std::string::npos) {
                std::string key = line.substr(0, colon);
                std::string value = line.substr(colon + 1);
                key.erase(key.begin(), std::find_if(key.begin(), key.end(), [](unsigned char ch) { return !std::isspace(ch); }));
                key.erase(std::find_if(key.rbegin(), key.rend(), [](unsigned char ch) { return !std::isspace(ch); }).base(), key.end());
                value.erase(value.begin(), std::find_if(value.begin(), value.end(), [](unsigned char ch) { return !std::isspace(ch); }));
                value.erase(std::find_if(value.rbegin(), value.rend(), [](unsigned char ch) { return !std::isspace(ch); }).base(), value.end());
                request.headers.emplace(std::move(key), std::move(value));
            }
        }

        std::ostringstream body;
        body << iss.rdbuf();
        request.body = body.str();
        return request;
    }

    std::string buildResponse(const HttpResponse& response) const {
        std::ostringstream oss;
        oss << "HTTP/1.1 " << response.status_code << " ";
        switch (response.status_code) {
            case 200: oss << "OK"; break;
            case 201: oss << "Created"; break;
            case 204: oss << "No Content"; break;
            case 400: oss << "Bad Request"; break;
            case 404: oss << "Not Found"; break;
            case 500: oss << "Internal Server Error"; break;
            default: oss << "Unknown"; break;
        }
        oss << "\r\n";
        oss << "Content-Length: " << response.body.size() << "\r\n";
        for (const auto& header : response.headers) {
            oss << header.first << ": " << header.second << "\r\n";
        }
        oss << "\r\n";
        oss << response.body;
        return oss.str();
    }

    bool matchRoute(const std::string& method,
                    const std::string& path,
                    Route& route,
                    std::map<std::string, std::string>& params) const {
        if (method != route.method) {
            return false;
        }
        std::smatch matches;
        if (std::regex_match(path, matches, route.regex)) {
            for (size_t i = 0; i < route.params.size(); ++i) {
                params[route.params[i]] = matches[i + 1];
            }
            return true;
        }
        return false;
    }
};

HttpResponse jsonResponse(const Json::Value& value, int status = 200) {
    HttpResponse response;
    response.status_code = status;
    Json::StreamWriterBuilder builder;
    response.body = Json::writeString(builder, value);
    return response;
}

HttpResponse errorResponse(const std::string& message, int status = 400) {
    Json::Value error;
    error["success"] = false;
    error["message"] = message;
    return jsonResponse(error, status);
}

Json::Value successPayload() {
    Json::Value root(Json::objectValue);
    root["success"] = true;
    return root;
}

va::analyzer::AnalyzerParams buildParamsFromJson(const Json::Value& json) {
    va::analyzer::AnalyzerParams params;
    if (json.isMember("conf")) {
        params.confidence_threshold = static_cast<float>(json["conf"].asDouble());
    }
    if (json.isMember("iou")) {
        params.iou_threshold = static_cast<float>(json["iou"].asDouble());
    }
    return params;
}

va::core::EngineDescriptor buildEngineDescriptor(const Json::Value& json) {
    va::core::EngineDescriptor descriptor;
    descriptor.name = json.isMember("type") ? json["type"].asString() : "";
    descriptor.provider = json.isMember("provider") ? json["provider"].asString() : descriptor.name;
    descriptor.device_index = json.isMember("device") ? json["device"].asInt() : 0;

    if (json.isMember("options") && json["options"].isObject()) {
        for (const auto& name : json["options"].getMemberNames()) {
            descriptor.options[name] = json["options"][name].asString();
        }
    }
    return descriptor;
}

} // namespace

struct RestServer::Impl {
    RestServerOptions options;
    va::app::Application& app;
    SimpleHttpServer server;

    Impl(RestServerOptions opts, va::app::Application& application)
        : options(std::move(opts)), app(application), server(options) {
        registerRoutes();
    }

    void registerRoutes() {
        auto subscribeHandler = [this](const HttpRequest& req) { return handleSubscribe(req); };
        auto unsubscribeHandler = [this](const HttpRequest& req) { return handleUnsubscribe(req); };
        auto sourceSwitchHandler = [this](const HttpRequest& req) { return handleSourceSwitch(req); };
        auto modelSwitchHandler = [this](const HttpRequest& req) { return handleModelSwitch(req); };
        auto taskSwitchHandler = [this](const HttpRequest& req) { return handleTaskSwitch(req); };
        auto paramsUpdateHandler = [this](const HttpRequest& req) { return handleParamsUpdate(req); };
        auto setEngineHandler = [this](const HttpRequest& req) { return handleSetEngine(req); };

        server.addRoute("POST", "/subscribe", subscribeHandler);
        server.addRoute("POST", "/api/subscribe", subscribeHandler);

        server.addRoute("POST", "/unsubscribe", unsubscribeHandler);
        server.addRoute("POST", "/api/unsubscribe", unsubscribeHandler);

        server.addRoute("POST", "/source/switch", sourceSwitchHandler);
        server.addRoute("POST", "/api/source/switch", sourceSwitchHandler);

        server.addRoute("POST", "/model/switch", modelSwitchHandler);
        server.addRoute("POST", "/api/model/switch", modelSwitchHandler);

        server.addRoute("POST", "/task/switch", taskSwitchHandler);
        server.addRoute("POST", "/api/task/switch", taskSwitchHandler);

        server.addRoute("PATCH", "/model/params", paramsUpdateHandler);
        server.addRoute("PATCH", "/api/model/params", paramsUpdateHandler);

        server.addRoute("POST", "/engine/set", setEngineHandler);
        server.addRoute("POST", "/api/engine/set", setEngineHandler);

        // Logging config: runtime set
        auto loggingSetHandler = [this](const HttpRequest& req) { return handleLoggingSet(req); };
        server.addRoute("POST", "/api/logging/set", loggingSetHandler);

        auto systemInfoHandler = [this](const HttpRequest& req) { return handleSystemInfo(req); };
        auto systemStatsHandler = [this](const HttpRequest& req) { return handleSystemStats(req); };
        auto modelsHandler = [this](const HttpRequest& req) { return handleModels(req); };
        auto profilesHandler = [this](const HttpRequest& req) { return handleProfiles(req); };
        auto pipelinesHandler = [this](const HttpRequest& req) { return handlePipelines(req); };

        server.addRoute("GET", "/system/info", systemInfoHandler);
        server.addRoute("GET", "/api/system/info", systemInfoHandler);

        server.addRoute("GET", "/system/stats", systemStatsHandler);
        server.addRoute("GET", "/api/system/stats", systemStatsHandler);

        server.addRoute("GET", "/models", modelsHandler);
        server.addRoute("GET", "/api/models", modelsHandler);

        server.addRoute("GET", "/profiles", profilesHandler);
        server.addRoute("GET", "/api/profiles", profilesHandler);

        server.addRoute("GET", "/pipelines", pipelinesHandler);
        server.addRoute("GET", "/api/pipelines", pipelinesHandler);

        // Prometheus metrics endpoint
        auto metricsHandler = [this](const HttpRequest& req) { return handleMetrics(req); };
        server.addRoute("GET", "/metrics", metricsHandler);
    }

    bool start() {
        return server.start();
    }

    void stop() {
        server.stop();
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
        data["observability"] = observability;

        Json::Value sfu(Json::objectValue);
        sfu["whip_base"] = config.sfu_whip_base;
        sfu["whep_base"] = config.sfu_whep_base;
        data["sfu"] = sfu;

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

    HttpResponse handleSystemStats(const HttpRequest& /*req*/) {
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

    HttpResponse handleMetrics(const HttpRequest& /*req*/) {
        // Prometheus text exposition format (0.0.4)
        auto sys = app.systemStats();
        auto gm = va::core::GlobalMetrics::snapshot();

        std::ostringstream out;
        out << "# HELP va_pipelines_total Total pipelines\n";
        out << "# TYPE va_pipelines_total gauge\n";
        out << "va_pipelines_total " << sys.total_pipelines << "\n";

        out << "# HELP va_pipelines_running Running pipelines\n";
        out << "# TYPE va_pipelines_running gauge\n";
        out << "va_pipelines_running " << sys.running_pipelines << "\n";

        out << "# HELP va_pipeline_aggregate_fps Aggregate FPS across pipelines\n";
        out << "# TYPE va_pipeline_aggregate_fps gauge\n";
        out << "va_pipeline_aggregate_fps " << sys.aggregate_fps << "\n";

        out << "# HELP va_frames_processed_total Frames processed (sum)\n";
        out << "# TYPE va_frames_processed_total counter\n";
        out << "va_frames_processed_total " << sys.processed_frames << "\n";

        out << "# HELP va_frames_dropped_total Frames dropped (sum)\n";
        out << "# TYPE va_frames_dropped_total counter\n";
        out << "va_frames_dropped_total " << sys.dropped_frames << "\n";

        out << "# HELP va_transport_packets_total Transport packets sent (sum)\n";
        out << "# TYPE va_transport_packets_total counter\n";
        out << "va_transport_packets_total " << sys.transport_packets << "\n";

        out << "# HELP va_transport_bytes_total Transport bytes sent (sum)\n";
        out << "# TYPE va_transport_bytes_total counter\n";
        out << "va_transport_bytes_total " << sys.transport_bytes << "\n";

        out << "# HELP va_d2d_nv12_frames_total NVENC device NV12 direct-feed frames\n";
        out << "# TYPE va_d2d_nv12_frames_total counter\n";
        out << "va_d2d_nv12_frames_total " << gm.d2d_nv12_frames << "\n";

        out << "# HELP va_cpu_fallback_skips_total CPU upload skipped (device NV12 path)\n";
        out << "# TYPE va_cpu_fallback_skips_total counter\n";
        out << "va_cpu_fallback_skips_total " << gm.cpu_fallback_skips << "\n";

        out << "# HELP va_encoder_eagain_retry_total Encoder EAGAIN drain+retry occurrences\n";
        out << "# TYPE va_encoder_eagain_retry_total counter\n";
        out << "va_encoder_eagain_retry_total " << gm.eagain_retry_count << "\n";

        out << "# HELP va_overlay_nv12_kernel_hits_total NV12 kernel overlay executions\n";
        out << "# TYPE va_overlay_nv12_kernel_hits_total counter\n";
        out << "va_overlay_nv12_kernel_hits_total " << gm.overlay_nv12_kernel_hits << "\n";

        out << "# HELP va_overlay_nv12_passthrough_total NV12 overlay passthrough (no boxes)\n";
        out << "# TYPE va_overlay_nv12_passthrough_total counter\n";
        out << "va_overlay_nv12_passthrough_total " << gm.overlay_nv12_passthrough << "\n";

        // Per-source metrics (labels: source_id, path)
        auto classify_path = [](const va::core::TrackManager::PipelineInfo& info) -> std::string {
            if (info.zc.d2d_nv12_frames > 0) return "d2d";
            std::string lower = info.encoder_cfg.codec;
            std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
            if (lower.find("nvenc") != std::string::npos) return "gpu";
            return "cpu";
        };

        // Per-pipeline FPS gauge
        out << "# HELP va_pipeline_fps Pipeline FPS per source\n";
        out << "# TYPE va_pipeline_fps gauge\n";
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            out << "va_pipeline_fps{source_id=\"" << info.stream_id
                << "\",path=\"" << path << "\"} " << info.metrics.fps << "\n";
        }

        // Per-pipeline frames processed/dropped with labels
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            out << "va_frames_processed_total{source_id=\"" << info.stream_id
                << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(info.metrics.processed_frames) << "\n";
            out << "va_frames_dropped_total{source_id=\"" << info.stream_id
                << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(info.metrics.dropped_frames) << "\n";
        }

        // Per-stage latency histograms per source
        const double bounds_ms[10] = {1,2,5,10,20,50,100,200,500,1000};
        out << "# HELP va_frame_latency_ms Frame processing latency per stage\n";
        out << "# TYPE va_frame_latency_ms histogram\n";
        auto emit_hist = [&](const std::string& stage,
                             const std::string& source_id,
                             const std::string& path,
                             const va::core::Pipeline::LatencySnapshot& snap) {
            uint64_t cumulative = 0;
            for (int i=0;i<va::core::Pipeline::LatencySnapshot::kNumBuckets; ++i) {
                cumulative += snap.buckets[i];
                out << "va_frame_latency_ms_bucket{stage=\"" << stage
                    << "\",source_id=\"" << source_id
                    << "\",path=\"" << path
                    << "\",le=\"" << bounds_ms[i] << "\"} "
                    << static_cast<unsigned long long>(cumulative) << "\n";
            }
            // +Inf bucket equals total count
            out << "va_frame_latency_ms_bucket{stage=\"" << stage
                << "\",source_id=\"" << source_id
                << "\",path=\"" << path
                << "\",le=\"+Inf\"} "
                << static_cast<unsigned long long>(snap.count) << "\n";
            // sum (ms) and count
            double sum_ms = static_cast<double>(snap.sum_us) / 1000.0;
            out << "va_frame_latency_ms_sum{stage=\"" << stage
                << "\",source_id=\"" << source_id
                << "\",path=\"" << path << "\"} " << sum_ms << "\n";
            out << "va_frame_latency_ms_count{stage=\"" << stage
                << "\",source_id=\"" << source_id
                << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(snap.count) << "\n";
        };
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            emit_hist("preproc", info.stream_id, path, info.stage_latency.preproc);
            emit_hist("infer",   info.stream_id, path, info.stage_latency.infer);
            emit_hist("postproc",info.stream_id, path, info.stage_latency.postproc);
            emit_hist("encode",  info.stream_id, path, info.stage_latency.encode);
        }

        // Frames dropped by reason (per-source)
        {
            auto rows = va::core::DropMetrics::snapshot();
            out << "# HELP va_frames_dropped_total Frames dropped by reason\n";
            out << "# TYPE va_frames_dropped_total counter\n";
            for (const auto& row : rows) {
                auto emit = [&](const char* reason, uint64_t val){
                    if (val == 0) return; // reduce noise
                    out << "va_frames_dropped_total{source_id=\"" << row.source_id
                        << "\",reason=\"" << reason << "\"} "
                        << static_cast<unsigned long long>(val) << "\n";
                };
                emit("queue_overflow", row.counters.queue_overflow);
                emit("decode_error",   row.counters.decode_error);
                emit("encode_eagain",  row.counters.encode_eagain);
                emit("backpressure",   row.counters.backpressure);
            }
        }

        // RTSP source reconnects per source
        {
            auto rows = va::core::SourceReconnects::snapshot();
            out << "# HELP va_rtsp_source_reconnects_total RTSP source reconnects\n";
            out << "# TYPE va_rtsp_source_reconnects_total counter\n";
            for (const auto& row : rows) {
                out << "va_rtsp_source_reconnects_total{source_id=\"" << row.source_id << "\"} "
                    << static_cast<unsigned long long>(row.reconnects) << "\n";
            }
        }

        // NVDEC device-path recovery and await-IDR events per source
        {
            auto rows = va::core::NvdecEvents::snapshot();
            out << "# HELP va_nvdec_device_recover_total NVDEC device-path recovery events\n";
            out << "# TYPE va_nvdec_device_recover_total counter\n";
            for (const auto& row : rows) {
                out << "va_nvdec_device_recover_total{source_id=\"" << row.source_id << "\"} "
                    << static_cast<unsigned long long>(row.device_recover) << "\n";
            }
            out << "# HELP va_nvdec_await_idr_total NVDEC await-IDR occurrences (startup/reopen)\n";
            out << "# TYPE va_nvdec_await_idr_total counter\n";
            for (const auto& row : rows) {
                out << "va_nvdec_await_idr_total{source_id=\"" << row.source_id << "\"} "
                    << static_cast<unsigned long long>(row.await_idr) << "\n";
            }
        }

        // Encoder metrics per source (use transport stats as proxy for encoded output)
        out << "# HELP va_encoder_packets_total Encoded packets per source\n";
        out << "# TYPE va_encoder_packets_total counter\n";
        out << "# HELP va_encoder_bytes_total Encoded bytes per source\n";
        out << "# TYPE va_encoder_bytes_total counter\n";
        out << "# HELP va_encoder_eagain_total Encoder EAGAIN occurrences per source\n";
        out << "# TYPE va_encoder_eagain_total counter\n";
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            const std::string codec = info.encoder_cfg.codec;
            out << "va_encoder_packets_total{source_id=\"" << info.stream_id
                << "\",codec=\"" << codec << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(info.transport_stats.packets) << "\n";
            out << "va_encoder_bytes_total{source_id=\"" << info.stream_id
                << "\",codec=\"" << codec << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(info.transport_stats.bytes) << "\n";
            out << "va_encoder_eagain_total{source_id=\"" << info.stream_id
                << "\",codec=\"" << codec << "\",path=\"" << path << "\"} "
                << static_cast<unsigned long long>(info.zc.eagain_retry_count) << "\n";
        }

        HttpResponse resp;
        resp.status_code = 200;
        resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8";
        resp.body = out.str();
        return resp;
    }

    static va::core::LogLevel parseLevelStr(const std::string& s) {
        std::string v = toLower(s);
        if (v == "trace") return va::core::LogLevel::Trace;
        if (v == "debug") return va::core::LogLevel::Debug;
        if (v == "warn" || v == "warning") return va::core::LogLevel::Warn;
        if (v == "error" || v == "err") return va::core::LogLevel::Error;
        return va::core::LogLevel::Info;
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
                            auto trim = [](std::string& x){ x.erase(0, x.find_first_not_of(" \t")); x.erase(x.find_last_not_of(" \t") + 1); };
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

    HttpResponse handleModels(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::arrayValue);
        for (const auto& model : app.detectionModels()) {
            data.append(modelToJson(model));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

    HttpResponse handleProfiles(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::arrayValue);
        for (const auto& profile : app.profiles()) {
            data.append(profileToJson(profile));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

    HttpResponse handlePipelines(const HttpRequest& /*req*/) {
        Json::Value payload = successPayload();
        Json::Value data(Json::arrayValue);
        for (const auto& info : app.pipelines()) {
            Json::Value node(Json::objectValue);
            node["key"] = info.key;
            node["stream_id"] = info.stream_id;
            node["profile_id"] = info.profile_id;
            node["source_uri"] = info.source_uri;
            node["model_id"] = info.model_id;
            node["task"] = info.task;
            node["running"] = info.running;
            node["last_active_ms"] = info.last_active_ms;
            node["track_id"] = info.track_id;
            node["metrics"] = metricsToJson(info.metrics);
            // Per-pipeline zero-copy metrics
            {
                Json::Value z(Json::objectValue);
                z["d2d_nv12_frames"] = static_cast<Json::UInt64>(info.zc.d2d_nv12_frames);
                z["cpu_fallback_skips"] = static_cast<Json::UInt64>(info.zc.cpu_fallback_skips);
                z["eagain_retry_count"] = static_cast<Json::UInt64>(info.zc.eagain_retry_count);
                z["overlay_nv12_kernel_hits"] = static_cast<Json::UInt64>(info.zc.overlay_nv12_kernel_hits);
                z["overlay_nv12_passthrough"] = static_cast<Json::UInt64>(info.zc.overlay_nv12_passthrough);
                node["zerocopy_metrics"] = z;
            }
            node["transport_stats"] = transportStatsToJson(info.transport_stats);
            node["encoder"] = encoderConfigToJson(info.encoder_cfg);
            data.append(std::move(node));
        }
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

    HttpResponse handleSubscribe(const HttpRequest& req) {
        try {
            const Json::Value body = parseJson(req.body);

            auto stream_opt = getStringField(body, {"stream_id", "stream"});
            if (!stream_opt) {
                VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing stream identifier";
                return errorResponse("Missing required field: stream_id", 400);
            }

            auto profile_opt = getStringField(body, {"profile", "profile_id"});
            if (!profile_opt) {
                VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing profile";
                return errorResponse("Missing required field: profile", 400);
            }

            auto uri_opt = getStringField(body, {"source_uri", "url"});
            if (!uri_opt) {
                VA_LOG_C(::va::core::LogLevel::Warn, "rest") << "subscribe missing source URI";
                return errorResponse("Missing required field: source_uri", 400);
            }

            const std::string stream_id = *stream_opt;
            const std::string profile = *profile_opt;
            const std::string uri = *uri_opt;

            VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe request stream=" << stream_id
                          << " profile=" << profile
                          << " uri=" << uri;
            std::optional<std::string> model_override;
            if (body.isMember("model_id") && body["model_id"].isString()) {
                model_override = body["model_id"].asString();
            }

            VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe -> building pipeline...";
            auto result = app.subscribeStream(stream_id, profile, uri, model_override);
            if (!result) {
                return errorResponse(app.lastError(), 400);
            }
            VA_LOG_C(::va::core::LogLevel::Info, "rest") << "subscribe -> pipeline created key=" << *result;

            Json::Value payload = successPayload();
            Json::Value data(Json::objectValue);
            data["subscription_id"] = *result;
            data["pipeline_key"] = *result;
            data["stream_id"] = stream_id;
            data["profile"] = profile;
            if (model_override) {
                data["model_id"] = *model_override;
            }
            payload["data"] = data;
            return jsonResponse(payload, 201);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

    HttpResponse handleUnsubscribe(const HttpRequest& req) {
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

            const bool success = app.unsubscribeStream(*stream_opt, *profile_opt);
            if (!success) {
                return errorResponse(app.lastError().empty() ? "unsubscribe failed" : app.lastError(), 400);
            }

            Json::Value payload = successPayload();
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

    HttpResponse handleSourceSwitch(const HttpRequest& req) {
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

            auto uri_opt = getStringField(body, {"source_uri", "url"});
            if (!uri_opt) {
                return errorResponse("Missing required field: source_uri", 400);
            }

            if (!app.switchSource(*stream_opt, *profile_opt, *uri_opt)) {
                return errorResponse(app.lastError().empty() ? "switch source failed" : app.lastError(), 400);
            }

            Json::Value payload = successPayload();
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

    HttpResponse handleModelSwitch(const HttpRequest& req) {
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

            auto model_opt = getStringField(body, {"model_id"});
            if (!model_opt) {
                return errorResponse("Missing required field: model_id", 400);
            }

            if (!app.switchModel(*stream_opt, *profile_opt, *model_opt)) {
                return errorResponse(app.lastError().empty() ? "switch model failed" : app.lastError(), 400);
            }

            Json::Value payload = successPayload();
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

    HttpResponse handleTaskSwitch(const HttpRequest& req) {
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

            auto task_opt = getStringField(body, {"task", "task_id"});
            if (!task_opt) {
                return errorResponse("Missing required field: task", 400);
            }

            if (!app.switchTask(*stream_opt, *profile_opt, *task_opt)) {
                return errorResponse(app.lastError().empty() ? "switch task failed" : app.lastError(), 400);
            }

            Json::Value payload = successPayload();
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
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

    HttpResponse handleSetEngine(const HttpRequest& req) {
        try {
            const Json::Value body = parseJson(req.body);
            if (!body.isMember("type") || !body["type"].isString()) {
                return errorResponse("Missing required field: type", 400);
            }

            auto descriptor = buildEngineDescriptor(body);
            if (!app.setEngine(descriptor)) {
                return errorResponse(app.lastError().empty() ? "set engine failed" : app.lastError(), 400);
            }

            Json::Value payload = successPayload();
            payload["type"] = descriptor.name;
            payload["provider"] = descriptor.provider;
            payload["device"] = descriptor.device_index;
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }
};

RestServer::RestServer(RestServerOptions options, va::app::Application& app)
    : options_(std::move(options)), app_(app), impl_(std::make_unique<Impl>(options_, app_)) {}

RestServer::~RestServer() {
    stop();
}

bool RestServer::start() {
    return impl_ ? impl_->start() : false;
}

void RestServer::stop() {
    if (impl_) {
        impl_->stop();
    }
}

} // namespace va::server
