#include "server/rest.hpp"

#include "app/application.hpp"
#include "analyzer/analyzer.hpp"
#include "core/engine_manager.hpp"
#include "core/logger.hpp"
#include "core/global_metrics.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"
#include "core/nvdec_events.hpp"
#include "core/metrics_text_builder.hpp"

#include "storage/db_pool.hpp"
#include "storage/log_repo.hpp"
#include "storage/event_repo.hpp"
#include "storage/session_repo.hpp"

#include <json/json.h>
#include "core/error_codes.hpp"
#include <yaml-cpp/yaml.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstddef>
#include <initializer_list>
#include <filesystem>
#include <map>
#include <mutex>
#include <condition_variable>
#include <optional>
#include <regex>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <utility>
#include <vector>
#include <ctime>

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
    using StreamHandler = std::function<void(int /*client_socket*/, const HttpRequest&)>;

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

    void addStreamRoute(const std::string& method, const std::string& pattern, StreamHandler handler) {
        std::lock_guard<std::mutex> lock(routes_mutex_);
        stream_routes_.push_back(StreamRoute{method, pattern, buildRegex(pattern), extractParams(pattern), std::move(handler)});
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

    struct StreamRoute {
        std::string method;
        std::string pattern;
        std::regex regex;
        std::vector<std::string> params;
        StreamHandler handler;
    };

    RestServerOptions options_;
    std::atomic<bool> running_ {false};
    std::thread server_thread_;
    std::mutex routes_mutex_;
    std::vector<Route> routes_;
    std::vector<StreamRoute> stream_routes_;
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

        // SSE streaming routes: handled specially (write headers and stream data; no Content-Length)
        {
            bool matched_stream = false;
            std::lock_guard<std::mutex> lock(routes_mutex_);
            for (auto& route : stream_routes_) {
                std::map<std::string, std::string> params;
                if (matchRoute(request.method, request.path, route, params)) {
                    request.params = std::move(params);
                    try {
                        route.handler(client_socket, request);
                    } catch (...) {
                        // best-effort: close socket
                    }
#ifdef _WIN32
                    closesocket(client_socket);
#else
                    close(client_socket);
#endif
                    return;
                }
            }
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

    bool matchRoute(const std::string& method,
                    const std::string& path,
                    StreamRoute& route,
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
    // Map HTTP status to a canonical error code string
    va::core::errors::ErrorCode ec = va::core::errors::from_http_status(status);
    error["code"] = va::core::errors::to_string(ec);
    error["message"] = message;
    return jsonResponse(error, status);
}

Json::Value successPayload() {
    Json::Value root(Json::objectValue);
    root["success"] = true;
    root["code"] = "OK";
    return root;
}

std::unordered_map<std::string,std::string> parseQueryKV(const std::string& q) {
    std::unordered_map<std::string,std::string> kv;
    if (q.empty()) return kv;
    size_t pos = 0;
    while (pos < q.size()) {
        auto eq = q.find('=', pos);
        if (eq == std::string::npos) break;
        auto amp = q.find('&', eq+1);
        std::string key = q.substr(pos, eq-pos);
        std::string val = amp==std::string::npos ? q.substr(eq+1) : q.substr(eq+1, amp-eq-1);
        // decode + and %XX
        auto decode = [](const std::string& in){ std::string out; out.reserve(in.size()); for (size_t i=0;i<in.size();++i){ if(in[i]=='+') out.push_back(' '); else if(in[i]=='%' && i+2<in.size()){ char hex[3] = {in[i+1], in[i+2], 0}; int v = 0; try { v = std::stoi(hex, nullptr, 16); } catch(...){} out.push_back(static_cast<char>(v)); i+=2; } else out.push_back(in[i]); } return out; };
        // lower-case key to ease matching
        std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
        kv[key] = decode(val);
        if (amp == std::string::npos) break;
        pos = amp + 1;
    }
    return kv;
}

// --- Minimal HTTP client (best-effort) for Control Plane to query VSM REST ---
static std::optional<std::string> http_get_body(const std::string& host, int port, const std::string& path, int timeout_ms) {
#ifdef _WIN32
    SOCKET sock = INVALID_SOCKET;
    addrinfo hints{}; hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM; hints.ai_protocol = IPPROTO_TCP;
    addrinfo* result = nullptr;
    std::string port_str = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &result) != 0 || !result) {
        return std::nullopt;
    }
    sock = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    if (sock == INVALID_SOCKET) { freeaddrinfo(result); return std::nullopt; }
    // timeouts
    int to = timeout_ms; setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&to), sizeof(to));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&to), sizeof(to));
    if (connect(sock, result->ai_addr, static_cast<int>(result->ai_addrlen)) == SOCKET_ERROR) {
        closesocket(sock); freeaddrinfo(result); return std::nullopt;
    }
    freeaddrinfo(result);
    std::ostringstream req;
    req << "GET " << path << " HTTP/1.1\r\n";
    req << "Host: " << host << "\r\n";
    req << "Connection: close\r\n\r\n";
    std::string reqs = req.str();
    int sent = 0; while (sent < static_cast<int>(reqs.size())) {
        int n = send(sock, reqs.c_str() + sent, static_cast<int>(reqs.size()) - sent, 0);
        if (n <= 0) { closesocket(sock); return std::nullopt; }
        sent += n;
    }
    std::string resp; resp.reserve(4096);
    char buf[4096];
    for(;;){ int n = recv(sock, buf, sizeof(buf), 0); if (n <= 0) break; resp.append(buf, buf + n); }
    closesocket(sock);
    auto pos = resp.find("\r\n\r\n"); if (pos == std::string::npos) return std::nullopt; return resp.substr(pos + 4);
#else
    (void)host; (void)port; (void)path; (void)timeout_ms; return std::nullopt;
#endif
}

static std::optional<Json::Value> vsm_sources_snapshot(int timeout_ms) {
    std::string host = "127.0.0.1";
    int port = 7071;
    if (const char* p = std::getenv("VSM_REST_HOST")) host = p;
    if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) port = v; } catch (...) {} }
    auto body = http_get_body(host, port, "/api/source/list", timeout_ms);
    if (!body) return std::nullopt;
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream iss(*body); Json::Value root; if (!Json::parseFromStream(b, iss, &root, &errs)) return std::nullopt;
        if (root.isObject() && root.isMember("data") && root["data"].isArray()) return root["data"];
        if (root.isArray()) return root;
    } catch (...) {}
    return std::nullopt;
}

static std::optional<Json::Value> vsm_source_describe(const std::string& id, int timeout_ms) {
    std::string host = "127.0.0.1";
    int port = 7071;
    if (const char* p = std::getenv("VSM_REST_HOST")) host = p;
    if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) port = v; } catch (...) {} }
    std::string path = std::string("/api/source/describe?id=") + id;
    auto body = http_get_body(host, port, path, timeout_ms);
    if (!body) return std::nullopt;
    try {
        Json::CharReaderBuilder b; std::string errs; std::istringstream iss(*body); Json::Value root; if (!Json::parseFromStream(b, iss, &root, &errs)) return std::nullopt;
        if (root.isObject() && root.isMember("data") && root["data"].isObject()) return root["data"];
        if (root.isObject()) return root;
    } catch (...) {}
    return std::nullopt;
}

// --- YAML helpers to extract 'requires' and map to JSON ---
namespace {
static Json::Value yamlToJsonObject(const YAML::Node& n) {
    Json::Value obj(Json::objectValue);
    if (!n || !n.IsMap()) return obj;
    for (auto it : n) {
        std::string key;
        try { key = it.first.as<std::string>(""); } catch (...) { continue; }
        const YAML::Node& val = it.second;
        if (val.IsScalar()) {
            obj[key] = val.as<std::string>("");
        } else if (val.IsSequence()) {
            Json::Value arr(Json::arrayValue);
            for (std::size_t i=0;i<val.size();++i) {
                if (val[i].IsScalar()) arr.append(val[i].as<std::string>(""));
                else if (val[i].IsSequence()) {
                    std::string joined;
                    for (std::size_t j=0;j<val[i].size();++j) {
                        if (j) joined += ",";
                        joined += val[i][j].as<std::string>("");
                    }
                    arr.append(joined);
                } else if (val[i].IsMap()) {
                    // Best-effort: flatten map as k1:v1;k2:v2
                    std::string flat; bool first=true;
                    for (auto kv : val[i]) {
                        if (!first) flat += ";"; first=false;
                        flat += kv.first.as<std::string>("");
                        flat += ":";
                        flat += kv.second.as<std::string>("");
                    }
                    arr.append(flat);
                }
            }
            obj[key] = arr;
        } else if (val.IsMap()) {
            obj[key] = yamlToJsonObject(val);
        }
    }
    return obj;
}

static std::optional<Json::Value> loadRequiresFromYaml(const std::string& file) {
    try {
        YAML::Node root = YAML::LoadFile(file);
        YAML::Node req = root["requires"];
        if (!req || !req.IsMap()) {
            req = root["analyzer"]["multistage"]["requires"];
        }
        if (req && req.IsMap()) return yamlToJsonObject(req);
    } catch (...) { /* ignore */ }
    return std::nullopt;
}
} // anonymous namespace (YAML helpers)

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
    // Optional DB-backed storage
    std::shared_ptr<va::storage::DbPool> db_pool;
    std::unique_ptr<va::storage::LogRepo> logs_repo;
    std::unique_ptr<va::storage::EventRepo> events_repo;
    std::unique_ptr<va::storage::SessionRepo> sessions_repo;

    // Async DB writer (best-effort)
    std::mutex dbq_mutex;
    std::condition_variable dbq_cv;
    std::vector<va::storage::EventRow> q_events;
    std::vector<va::storage::LogRow> q_logs;
    std::unique_ptr<std::thread> db_thread;
    std::atomic<bool> db_stop{false};
    // Periodic DB retention worker (best-effort)
    std::unique_ptr<std::thread> retention_thread;
    std::atomic<bool> retention_stop{false};

    static std::uint64_t now_ms() {
        using namespace std::chrono;
        return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
    }

    void startDbWorker() {
        if (!events_repo && !logs_repo) return;
        db_stop.store(false, std::memory_order_relaxed);
        db_thread = std::make_unique<std::thread>([this]() {
            const auto flush_interval = std::chrono::milliseconds(500);
            for (;;) {
                std::vector<va::storage::EventRow> evts;
                std::vector<va::storage::LogRow> logs;
                {
                    std::unique_lock<std::mutex> lk(dbq_mutex);
                    dbq_cv.wait_for(lk, flush_interval, [this]{ return db_stop.load(std::memory_order_relaxed) || !q_events.empty() || !q_logs.empty(); });
                    if (db_stop.load(std::memory_order_relaxed) && q_events.empty() && q_logs.empty()) {
                        break;
                    }
                    evts.swap(q_events);
                    logs.swap(q_logs);
                }
                if (!evts.empty() && events_repo) {
                    std::string err; if (!events_repo->append(evts, &err)) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Error, "db", 5000) << "events append failed: " << err;
                    }
                }
                if (!logs.empty() && logs_repo) {
                    std::string err; if (!logs_repo->append(logs, &err)) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Error, "db", 5000) << "logs append failed: " << err;
                    }
                }
            }
        });
    }

    void stopDbWorker() {
        if (db_thread) {
            db_stop.store(true, std::memory_order_relaxed);
            dbq_cv.notify_all();
            if (db_thread->joinable()) db_thread->join();
            db_thread.reset();
        }
    }

    void startRetentionWorker() {
        const auto& r = app.appConfig().database.retention;
        if (!r.enabled) return;
        if (r.interval_seconds <= 0) return;
        if (!events_repo && !logs_repo) return;
        retention_stop.store(false, std::memory_order_relaxed);
        retention_thread = std::make_unique<std::thread>([this]() {
            const auto& r = app.appConfig().database.retention;
            auto interval = std::chrono::seconds(r.interval_seconds > 0 ? r.interval_seconds : 600);
            // Add simple jitter to avoid thundering herd when multiple instances start at same time
            auto jitter_pct = (r.jitter_percent >= 0 && r.jitter_percent <= 100) ? r.jitter_percent : 10;
            auto jitter_ms = (interval.count() * jitter_pct / 100) * 1000;
            if (jitter_ms < 0) jitter_ms = 0;
            {
                // initial jittered delay
                int64_t delay_ms = (jitter_ms > 0) ? (std::rand() % (jitter_ms + 1)) : 0;
                if (delay_ms > 0) std::this_thread::sleep_for(std::chrono::milliseconds(delay_ms));
            }
            while (!retention_stop.load(std::memory_order_relaxed)) {
                const auto start = std::chrono::steady_clock::now();
                if (events_repo && app.appConfig().database.retention.events_seconds > 0) {
                    std::string err; if (events_repo->purgeOlderThanSeconds(app.appConfig().database.retention.events_seconds, &err)) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Info, "db.retention", 10000) << "events purge ok";
                    } else if (!err.empty()) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "db.retention", 10000) << "events purge failed: " << err;
                    }
                }
                if (logs_repo && app.appConfig().database.retention.logs_seconds > 0) {
                    std::string err; if (logs_repo->purgeOlderThanSeconds(app.appConfig().database.retention.logs_seconds, &err)) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Info, "db.retention", 10000) << "logs purge ok";
                    } else if (!err.empty()) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "db.retention", 10000) << "logs purge failed: " << err;
                    }
                }
                // sleep until next interval (with jitter each round)
                auto elapsed = std::chrono::steady_clock::now() - start;
                auto remaining = interval - std::chrono::duration_cast<std::chrono::seconds>(elapsed);
                if (remaining.count() < 1) remaining = std::chrono::seconds(1);
                // add jitter again
                int64_t delay_ms = (jitter_ms > 0) ? (std::rand() % (jitter_ms + 1)) : 0;
                std::this_thread::sleep_for(remaining + std::chrono::milliseconds(delay_ms));
            }
        });
    }

    void stopRetentionWorker() {
        if (retention_thread) {
            retention_stop.store(true, std::memory_order_relaxed);
            if (retention_thread->joinable()) retention_thread->join();
            retention_thread.reset();
        }
    }

    void emitEvent(const std::string& level,
                   const std::string& type,
                   const std::string& pipeline,
                   const std::string& node,
                   const std::string& stream_id,
                   const std::string& msg,
                   const std::string& extra_json = std::string()) {
        if (!events_repo) return;
        va::storage::EventRow r;
        r.ts_ms = static_cast<std::int64_t>(now_ms());
        r.level = level; r.type = type; r.pipeline = pipeline; r.node = node; r.stream_id = stream_id; r.msg = msg; r.extra_json = extra_json;
        {
            std::lock_guard<std::mutex> lk(dbq_mutex);
            if (q_events.size() > 4096) q_events.clear();
            q_events.emplace_back(std::move(r));
        }
        dbq_cv.notify_one();
    }

    void emitLog(const std::string& level,
                 const std::string& pipeline,
                 const std::string& node,
                 const std::string& stream_id,
                 const std::string& message,
                 const std::string& extra_json = std::string()) {
        if (!logs_repo) return;
        va::storage::LogRow r;
        r.ts_ms = static_cast<std::int64_t>(now_ms());
        r.level = level; r.pipeline = pipeline; r.node = node; r.stream_id = stream_id; r.message = message; r.extra_json = extra_json;
        {
            std::lock_guard<std::mutex> lk(dbq_mutex);
            if (q_logs.size() > 4096) q_logs.clear();
            q_logs.emplace_back(std::move(r));
        }
        dbq_cv.notify_one();
    }

    Impl(RestServerOptions opts, va::app::Application& application)
        : options(std::move(opts)), app(application), server(options) {
        // Initialize DB pool and repositories if configured
        try {
            const auto& dbc = app.appConfig().database;
            if (!dbc.driver.empty() && toLower(dbc.driver) == "mysql" && !dbc.host.empty() && dbc.port > 0) {
                db_pool = va::storage::DbPool::create(dbc);
                if (db_pool && db_pool->valid()) {
                    logs_repo = std::make_unique<va::storage::LogRepo>(db_pool, dbc);
                    events_repo = std::make_unique<va::storage::EventRepo>(db_pool, dbc);
                    sessions_repo = std::make_unique<va::storage::SessionRepo>(db_pool, dbc);
                    startDbWorker();
                    startRetentionWorker();
                }
            }
        } catch (...) {
            // Best-effort: keep server running even if DB init fails
        }
        registerRoutes();
    }

    ~Impl() { stopDbWorker(); stopRetentionWorker(); }

    void registerRoutes() {
        auto subscribeHandler = [this](const HttpRequest& req) { return handleSubscribe(req); };
        auto unsubscribeHandler = [this](const HttpRequest& req) { return handleUnsubscribe(req); };
        auto sourceSwitchHandler = [this](const HttpRequest& req) { return handleSourceSwitch(req); };
        auto modelSwitchHandler = [this](const HttpRequest& req) { return handleModelSwitch(req); };
        auto taskSwitchHandler = [this](const HttpRequest& req) { return handleTaskSwitch(req); };
        auto paramsUpdateHandler = [this](const HttpRequest& req) { return handleParamsUpdate(req); };
        auto setEngineHandler = [this](const HttpRequest& req) { return handleSetEngine(req); };
        auto graphsListHandler = [this](const HttpRequest& req) { return handleGraphsList(req); };
        auto graphSwitchHandler = [this](const HttpRequest& req) { return handleGraphSwitch(req); };
        // Control-plane (embedded): ApplyPipeline / ApplyPipelines via REST
        auto cpApplyHandler = [this](const HttpRequest& req) { return handleCpApply(req); };
        auto cpApplyBatchHandler = [this](const HttpRequest& req) { return handleCpApplyBatch(req); };

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

        // Multistage graph management
        server.addRoute("GET", "/api/graphs", graphsListHandler);
        // Preflight compatibility check
        auto preflightHandler = [this](const HttpRequest& req) { return handlePreflight(req); };
        server.addRoute("POST", "/api/preflight", preflightHandler);
        server.addRoute("POST", "/api/graph/set", graphSwitchHandler);
        // Control-plane mapping
        server.addRoute("POST", "/api/control/apply_pipeline", cpApplyHandler);
        server.addRoute("POST", "/api/control/apply_pipelines", cpApplyBatchHandler);

        // Logging config: runtime set
        auto loggingSetHandler = [this](const HttpRequest& req) { return handleLoggingSet(req); };
        auto loggingGetHandler = [this](const HttpRequest& req) { return handleLoggingGet(req); };
        server.addRoute("POST", "/api/logging/set", loggingSetHandler);
        server.addRoute("GET", "/api/logging", loggingGetHandler);

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

        // Aggregated sources view + long-poll watch
        auto sourcesHandler = [this](const HttpRequest& req) { return handleSources(req); };
        auto sourcesWatchHandler = [this](const HttpRequest& req) { return handleSourcesWatch(req); };
        server.addRoute("GET", "/sources", sourcesHandler);
        server.addRoute("GET", "/api/sources", sourcesHandler);
        server.addRoute("GET", "/sources/watch", sourcesWatchHandler);
        server.addRoute("GET", "/api/sources/watch", sourcesWatchHandler);
        // SSE variants (experimental): watch via EventSource
        // server.addStreamRoute("GET", "/api/sources/watch_sse", [this](int fd, const HttpRequest& req){ streamSourcesSSE(fd, req); });

        // Prometheus metrics endpoint
        auto metricsHandler = [this](const HttpRequest& req) { return handleMetrics(req); };
        server.addRoute("GET", "/metrics", metricsHandler);
        auto metricsCfgGet = [this](const HttpRequest& req) { return handleMetricsConfigGet(req); };
        auto metricsCfgSet = [this](const HttpRequest& req) { return handleMetricsConfigSet(req); };
        server.addRoute("GET", "/api/metrics", metricsCfgGet);
        server.addRoute("POST", "/api/metrics/set", metricsCfgSet);

        // Observability: logs/events
        auto logsRecentHandler = [this](const HttpRequest& req) { return handleLogsRecent(req); };
        auto logsWatchHandler  = [this](const HttpRequest& req) { return handleLogsWatch(req); };
        auto eventsRecentHandler = [this](const HttpRequest& req) { return handleEventsRecent(req); };
        auto eventsWatchHandler  = [this](const HttpRequest& req) { return handleEventsWatch(req); };
        auto sessionsWatchHandler = [this](const HttpRequest& req) { return handleSessionsWatch(req); };
        server.addRoute("GET", "/api/logs", logsRecentHandler);
        server.addRoute("GET", "/api/logs/watch", logsWatchHandler);
        // SSE: logs
        server.addStreamRoute("GET", "/api/logs/watch_sse", [this](int fd, const HttpRequest& req){ streamLogsSSE(fd, req); });
        server.addRoute("GET", "/api/events/recent", eventsRecentHandler);
        server.addRoute("GET", "/api/events/watch", eventsWatchHandler);
        server.addRoute("GET", "/api/sessions/watch", sessionsWatchHandler);
        // SSE: events
        server.addStreamRoute("GET", "/api/events/watch_sse", [this](int fd, const HttpRequest& req){ streamEventsSSE(fd, req); });

        // Database: health check
        auto dbPingHandler = [this](const HttpRequest& req) { return handleDbPing(req); };
        server.addRoute("GET", "/api/db/ping", dbPingHandler);

        // Retention: manual purge endpoint (admin)
        auto dbPurgeHandler = [this](const HttpRequest& req) { return handleDbPurge(req); };
        server.addRoute("POST", "/api/db/retention/purge", dbPurgeHandler);

        // Sessions: list recent
        auto sessionsListHandler = [this](const HttpRequest& req) { return handleSessionsList(req); };
        server.addRoute("GET", "/api/sessions", sessionsListHandler);
    }

    bool start() {
        return server.start();
    }

    void stop() {
        server.stop();
    }

    HttpResponse handleCpApply(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            Json::Value body = parseJson(req.body);
            if (!body.isMember("pipeline_name") || !body["pipeline_name"].isString()) {
                return errorResponse("Missing required field: pipeline_name", 400);
            }
            va::control::PlainPipelineSpec spec;
            spec.name = body["pipeline_name"].asString();
            if (body.isMember("revision") && body["revision"].isString()) spec.revision = body["revision"].asString();
            if (body.isMember("graph_id") && body["graph_id"].isString()) spec.graph_id = body["graph_id"].asString();
            if (body.isMember("yaml_path") && body["yaml_path"].isString()) spec.yaml_path = body["yaml_path"].asString();
            if (body.isMember("template_id") && body["template_id"].isString()) spec.template_id = body["template_id"].asString();
            if (body.isMember("project") && body["project"].isString()) spec.project = body["project"].asString();
            if (body.isMember("tags") && body["tags"].isArray()) {
                for (const auto& t : body["tags"]) if (t.isString()) spec.tags.push_back(t.asString());
            }
            if (body.isMember("overrides") && body["overrides"].isObject()) {
                for (const auto& k : body["overrides"].getMemberNames()) {
                    spec.overrides[k] = body["overrides"][k].asString();
                }
            }
            // Require at least one of graph_id/yaml_path/template_id
            if (spec.graph_id.empty() && spec.yaml_path.empty() && spec.template_id.empty()) {
                return errorResponse("Missing graph_id/yaml_path/template_id", 400);
            }
            std::string err;
            bool ok = app.applyPipeline(spec, &err);
            if (!ok) return errorResponse(err.empty()? "apply failed" : err, 409);
            Json::Value payload = successPayload();
            payload["accepted"] = ok;
            // Record DB event/log (best-effort)
            emitEvent("info", "apply_pipeline", spec.name, "control", std::string(), std::string("apply ") + spec.name);
            emitLog("info", spec.name, "control", std::string(), "apply_pipeline accepted");
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(std::string("exception: ") + ex.what(), 500);
        }
#else
        return errorResponse("control-plane disabled", 503);
#endif
    }

    HttpResponse handleCpApplyBatch(const HttpRequest& req) {
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
        try {
            Json::Value body = parseJson(req.body);
            if (!body.isMember("items") || !body["items"].isArray()) {
                return errorResponse("Missing required array: items", 400);
            }
            std::vector<va::control::PlainPipelineSpec> items;
            for (const auto& it : body["items"]) {
                if (!it.isObject()) continue;
                va::control::PlainPipelineSpec spec;
                if (it.isMember("pipeline_name") && it["pipeline_name"].isString()) spec.name = it["pipeline_name"].asString();
                if (it.isMember("revision") && it["revision"].isString()) spec.revision = it["revision"].asString();
                if (it.isMember("graph_id") && it["graph_id"].isString()) spec.graph_id = it["graph_id"].asString();
                if (it.isMember("yaml_path") && it["yaml_path"].isString()) spec.yaml_path = it["yaml_path"].asString();
                if (it.isMember("template_id") && it["template_id"].isString()) spec.template_id = it["template_id"].asString();
                if (it.isMember("project") && it["project"].isString()) spec.project = it["project"].asString();
                if (it.isMember("tags") && it["tags"].isArray()) {
                    for (const auto& t : it["tags"]) if (t.isString()) spec.tags.push_back(t.asString());
                }
                if (it.isMember("overrides") && it["overrides"].isObject()) {
                    for (const auto& k : it["overrides"].getMemberNames()) spec.overrides[k] = it["overrides"][k].asString();
                }
                items.push_back(std::move(spec));
            }
            std::vector<std::string> errors;
            int accepted = app.applyPipelines(items, &errors);
            Json::Value payload = successPayload();
            payload["accepted"] = accepted;
            Json::Value errs(Json::arrayValue); for (const auto& e : errors) errs.append(e);
            payload["errors"] = errs;
            emitEvent("info", "apply_pipelines", std::string(), "control", std::string(), std::string("accepted=") + std::to_string(accepted));
            emitLog("info", std::string(), "control", std::string(), "apply_pipelines finished");
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(std::string("exception: ") + ex.what(), 500);
        }
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
          Json::Value payload = successPayload();
          Json::Value arr(Json::arrayValue);
          std::error_code ec;
          auto dirs = graphDirCandidates();
          std::unordered_set<std::string> files_seen;
          for (const auto& dir : dirs) {
              if (!std::filesystem::exists(dir, ec) || !std::filesystem::is_directory(dir, ec)) continue;
              for (auto& entry : std::filesystem::directory_iterator(dir, ec)) {
                  if (entry.is_regular_file(ec)) {
                      auto p = entry.path();
                      auto ext = p.extension().string();
                      if (ext == ".yaml" || ext == ".yml") {
                          auto can = std::filesystem::weakly_canonical(p, ec);
                          const std::string fkey = (ec ? p : can).string();
                          if (files_seen.count(fkey)) continue;
                          files_seen.insert(fkey);
                          Json::Value node(Json::objectValue);
                          node["id"] = p.stem().string();
                          node["path"] = fkey;
                          // Best-effort parse of optional 'requires'
                          try {
                              if (auto req = loadRequiresFromYaml(fkey)) {
                                  node["requires"] = *req;
                              }
                          } catch (...) { /* ignore */ }
                          arr.append(node);
                      }
                  }
              }
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
              return jsonResponse(payload, 200);
          } catch (const std::exception& ex) {
              return errorResponse(ex.what(), 400);
          }
      }

      // POST /api/preflight
      HttpResponse handlePreflight(const HttpRequest& req) {
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
              auto in_str_list = [](const Json::Value& arr, const std::string& s){ if(!arr.isArray() || !arr.size()) return true; for(const auto& x: arr){ if(x.isString() && x.asString()==s) return true; } return false; };

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
        const auto& obs = app.appConfig().observability;
        const bool use_registry = metrics_registry_enabled_.has_value() ? *metrics_registry_enabled_ : obs.metrics_registry_enabled;
        if (use_registry) {
            va::core::MetricsTextBuilder mb;
            // System metrics
            mb.header("va_pipelines_total", "gauge", "Total pipelines");
            mb.sample("va_pipelines_total", "{}", std::to_string(static_cast<unsigned long long>(sys.total_pipelines)));
            mb.header("va_pipelines_running", "gauge", "Running pipelines");
            mb.sample("va_pipelines_running", "{}", std::to_string(static_cast<unsigned long long>(sys.running_pipelines)));
            mb.header("va_pipeline_aggregate_fps", "gauge", "Aggregate FPS across pipelines");
            mb.sample("va_pipeline_aggregate_fps", "{}", sys.aggregate_fps);

            mb.header("va_frames_processed_total", "counter", "Frames processed (sum)");
            mb.sample("va_frames_processed_total", "{}", std::to_string(static_cast<unsigned long long>(sys.processed_frames)));
            mb.header("va_frames_dropped_total", "counter", "Frames dropped (sum)");
            mb.sample("va_frames_dropped_total", "{}", std::to_string(static_cast<unsigned long long>(sys.dropped_frames)));

            mb.header("va_transport_packets_total", "counter", "Transport packets sent (sum)");
            mb.sample("va_transport_packets_total", "{}", std::to_string(static_cast<unsigned long long>(sys.transport_packets)));
            mb.header("va_transport_bytes_total", "counter", "Transport bytes sent (sum)");
            mb.sample("va_transport_bytes_total", "{}", std::to_string(static_cast<unsigned long long>(sys.transport_bytes)));

            mb.header("va_d2d_nv12_frames_total", "counter", "NVENC device NV12 direct-feed frames");
            mb.sample("va_d2d_nv12_frames_total", "{}", std::to_string(static_cast<unsigned long long>(gm.d2d_nv12_frames)));
            mb.header("va_cpu_fallback_skips_total", "counter", "CPU upload skipped (device NV12 path)");
            mb.sample("va_cpu_fallback_skips_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cpu_fallback_skips)));
            mb.header("va_encoder_eagain_retry_total", "counter", "Encoder EAGAIN drain+retry occurrences");
            mb.sample("va_encoder_eagain_retry_total", "{}", std::to_string(static_cast<unsigned long long>(gm.eagain_retry_count)));
            mb.header("va_overlay_nv12_kernel_hits_total", "counter", "NV12 kernel overlay executions");
            mb.sample("va_overlay_nv12_kernel_hits_total", "{}", std::to_string(static_cast<unsigned long long>(gm.overlay_nv12_kernel_hits)));
            mb.header("va_overlay_nv12_passthrough_total", "counter", "NV12 overlay passthrough (no boxes)");
            mb.sample("va_overlay_nv12_passthrough_total", "{}", std::to_string(static_cast<unsigned long long>(gm.overlay_nv12_passthrough)));
            // Control-plane metrics
            mb.header("va_cp_auto_subscribe_total", "counter", "Auto subscribe events (success)");
            mb.sample("va_cp_auto_subscribe_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_subscribe_total)));
            mb.header("va_cp_auto_unsubscribe_total", "counter", "Auto unsubscribe events (success)");
            mb.sample("va_cp_auto_unsubscribe_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_unsubscribe_total)));
            mb.header("va_cp_auto_switch_source_total", "counter", "Auto source switch events (success)");
            mb.sample("va_cp_auto_switch_source_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_source_total)));
            mb.header("va_cp_auto_switch_model_total", "counter", "Auto model switch events (success)");
            mb.sample("va_cp_auto_switch_model_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_model_total)));
            mb.header("va_cp_auto_subscribe_failed_total", "counter", "Auto subscribe failures");
            mb.sample("va_cp_auto_subscribe_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_subscribe_failed_total)));
            mb.header("va_cp_auto_switch_source_failed_total", "counter", "Auto source switch failures");
            mb.sample("va_cp_auto_switch_source_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_source_failed_total)));
            mb.header("va_cp_auto_switch_model_failed_total", "counter", "Auto model switch failures");
            mb.sample("va_cp_auto_switch_model_failed_total", "{}", std::to_string(static_cast<unsigned long long>(gm.cp_auto_switch_model_failed_total)));

            // Helper functions
            auto classify_path = [](const va::core::TrackManager::PipelineInfo& info) -> std::string {
                if (info.zc.d2d_nv12_frames > 0) return "d2d";
                std::string lower = info.encoder_cfg.codec;
                std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
                if (lower.find("nvenc") != std::string::npos) return "gpu";
                return "cpu";
            };
            const bool ext_labels = metrics_extended_labels_.has_value() ? *metrics_extended_labels_ : obs.metrics_extended_labels;
            auto lbl = [&](const va::core::TrackManager::PipelineInfo& pinfo, const std::string& path){
                std::ostringstream oss;
                oss << "{source_id=\"" << pinfo.stream_id << "\",path=\"" << path << "\"";
                if (ext_labels) {
                    if (!pinfo.decoder_label.empty()) oss << ",decoder=\"" << pinfo.decoder_label << "\"";
                    if (!pinfo.encoder_cfg.codec.empty()) oss << ",encoder=\"" << pinfo.encoder_cfg.codec << "\"";
                    std::string preproc = "cpu";
                    auto eng = app.currentEngine();
                    auto it = eng.options.find("use_cuda_preproc");
                    if (it != eng.options.end()) {
                        std::string v = toLower(it->second);
                        if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
                    }
                    oss << ",preproc=\"" << preproc << "\"";
                }
                oss << "}"; return oss.str(); };

            // Per-source FPS and frames
            mb.header("va_pipeline_fps", "gauge", "Pipeline FPS per source");
            for (const auto& info : app.pipelines()) {
                const std::string path = classify_path(info);
                mb.sample("va_pipeline_fps", lbl(info, path), info.metrics.fps);
            }
            mb.header("va_frames_processed_total", "counter", "Frames processed per source");
            mb.header("va_frames_dropped_total", "counter", "Frames dropped per source");
            for (const auto& info : app.pipelines()) {
                const std::string path = classify_path(info);
                mb.sample("va_frames_processed_total", lbl(info, path), info.metrics.processed_frames);
                mb.sample("va_frames_dropped_total", lbl(info, path), info.metrics.dropped_frames);
            }

            // Histograms (per stage)
            mb.header("va_frame_latency_ms", "histogram", "Frame processing latency per stage");
            const double bounds_ms[10] = {1,2,5,10,20,50,100,200,500,1000};
            auto emit_hist = [&](const std::string& stage,
                                 const va::core::TrackManager::PipelineInfo& info,
                                 const va::core::Pipeline::LatencySnapshot& snap) {
                const std::string path = classify_path(info);
                uint64_t cumulative = 0;
                for (int i=0;i<va::core::Pipeline::LatencySnapshot::kNumBuckets; ++i) {
                    cumulative += snap.buckets[i];
                    std::ostringstream ls; ls<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\",le=\""<<bounds_ms[i]<<"\"}";
                    mb.sample("va_frame_latency_ms_bucket", ls.str(), cumulative);
                }
                std::ostringstream linf; linf<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\",le=\"+Inf\"}";
                mb.sample("va_frame_latency_ms_bucket", linf.str(), snap.count);
                double sum_ms = static_cast<double>(snap.sum_us) / 1000.0;
                std::ostringstream lsum; lsum<<"{stage=\""<<stage<<"\",source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\"}";
                mb.sample("va_frame_latency_ms_sum", lsum.str(), sum_ms);
                mb.sample("va_frame_latency_ms_count", lsum.str(), snap.count);
            };
            for (const auto& info : app.pipelines()) {
                emit_hist("preproc", info, info.stage_latency.preproc);
                emit_hist("infer",   info, info.stage_latency.infer);
                emit_hist("postproc",info, info.stage_latency.postproc);
                emit_hist("encode",  info, info.stage_latency.encode);
            }

            // Drop reasons
            mb.header("va_frames_dropped_total", "counter", "Frames dropped by reason");
            for (const auto& row : va::core::DropMetrics::snapshot()) {
                auto emit = [&](const char* reason, uint64_t v){ if(!v) return; std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\",reason=\""<<reason<<"\"}"; mb.sample("va_frames_dropped_total", ls.str(), v);};
                emit("queue_overflow", row.counters.queue_overflow);
                emit("decode_error",   row.counters.decode_error);
                emit("encode_eagain",  row.counters.encode_eagain);
                emit("backpressure",   row.counters.backpressure);
            }

            // Encoder per-source
            mb.header("va_encoder_packets_total", "counter", "Encoded packets per source");
            mb.header("va_encoder_bytes_total", "counter", "Encoded bytes per source");
            mb.header("va_encoder_eagain_total", "counter", "Encoder EAGAIN occurrences per source");
            for (const auto& info : app.pipelines()) {
                const std::string path = classify_path(info);
                std::ostringstream ls; ls<<"{source_id=\""<<info.stream_id<<"\",path=\""<<path<<"\"";
                if (ext_labels && !info.encoder_cfg.codec.empty()) ls<<",encoder=\""<<info.encoder_cfg.codec<<"\"";
                if (ext_labels && !info.decoder_label.empty()) ls<<",decoder=\""<<info.decoder_label<<"\"";
                ls<<"}";
                mb.sample("va_encoder_packets_total", ls.str(), info.transport_stats.packets);
                mb.sample("va_encoder_bytes_total", ls.str(), info.transport_stats.bytes);
                mb.sample("va_encoder_eagain_total", ls.str(), info.zc.eagain_retry_count);
            }

            // Reconnects & NVDEC
            mb.header("va_rtsp_source_reconnects_total", "counter", "RTSP source reconnects");
            for (const auto& row : va::core::SourceReconnects::snapshot()) {
                std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\"}"; mb.sample("va_rtsp_source_reconnects_total", ls.str(), row.reconnects);
            }
            mb.header("va_nvdec_device_recover_total", "counter", "NVDEC device-path recovery events");
            mb.header("va_nvdec_await_idr_total", "counter", "NVDEC await-IDR occurrences (startup/reopen)");
            for (const auto& row : va::core::NvdecEvents::snapshot()) {
                std::ostringstream ls; ls<<"{source_id=\""<<row.source_id<<"\"}";
                mb.sample("va_nvdec_device_recover_total", ls.str(), row.device_recover);
                mb.sample("va_nvdec_await_idr_total", ls.str(), row.await_idr);
            }

            HttpResponse resp;
            resp.status_code = 200;
            resp.headers["Content-Type"] = "text/plain; version=0.0.4; charset=utf-8";
            resp.body = mb.str();
            return resp;
        }

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

        // Control-plane metrics (plain text branch)
        out << "# HELP va_cp_auto_subscribe_total Auto subscribe events (success)\n";
        out << "# TYPE va_cp_auto_subscribe_total counter\n";
        out << "va_cp_auto_subscribe_total " << gm.cp_auto_subscribe_total << "\n";

        out << "# HELP va_cp_auto_unsubscribe_total Auto unsubscribe events (success)\n";
        out << "# TYPE va_cp_auto_unsubscribe_total counter\n";
        out << "va_cp_auto_unsubscribe_total " << gm.cp_auto_unsubscribe_total << "\n";

        out << "# HELP va_cp_auto_switch_source_total Auto source switch events (success)\n";
        out << "# TYPE va_cp_auto_switch_source_total counter\n";
        out << "va_cp_auto_switch_source_total " << gm.cp_auto_switch_source_total << "\n";

        out << "# HELP va_cp_auto_switch_model_total Auto model switch events (success)\n";
        out << "# TYPE va_cp_auto_switch_model_total counter\n";
        out << "va_cp_auto_switch_model_total " << gm.cp_auto_switch_model_total << "\n";

        out << "# HELP va_cp_auto_subscribe_failed_total Auto subscribe failures\n";
        out << "# TYPE va_cp_auto_subscribe_failed_total counter\n";
        out << "va_cp_auto_subscribe_failed_total " << gm.cp_auto_subscribe_failed_total << "\n";

        out << "# HELP va_cp_auto_switch_source_failed_total Auto source switch failures\n";
        out << "# TYPE va_cp_auto_switch_source_failed_total counter\n";
        out << "va_cp_auto_switch_source_failed_total " << gm.cp_auto_switch_source_failed_total << "\n";

        out << "# HELP va_cp_auto_switch_model_failed_total Auto model switch failures\n";
        out << "# TYPE va_cp_auto_switch_model_failed_total counter\n";
        out << "va_cp_auto_switch_model_failed_total " << gm.cp_auto_switch_model_failed_total << "\n";

        // Per-source metrics (labels: source_id, path)
        auto classify_path = [](const va::core::TrackManager::PipelineInfo& info) -> std::string {
            if (info.zc.d2d_nv12_frames > 0) return "d2d";
            std::string lower = info.encoder_cfg.codec;
            std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c){ return static_cast<char>(std::tolower(c)); });
            if (lower.find("nvenc") != std::string::npos) return "gpu";
            return "cpu";
        };

        const bool ext_labels = app.appConfig().observability.metrics_extended_labels;
        // Helper to build label string with optional extended labels
        auto make_labels = [&](const std::string& source_id,
                               const std::string& path,
                               const va::core::TrackManager::PipelineInfo* pinfo) -> std::string {
            std::ostringstream oss;
            oss << "{source_id=\"" << source_id << "\",path=\"" << path << "\"";
            if (ext_labels && pinfo) {
                // decoder label
                if (!pinfo->decoder_label.empty()) {
                    oss << ",decoder=\"" << pinfo->decoder_label << "\"";
                }
                // encoder label (codec family)
                if (!pinfo->encoder_cfg.codec.empty()) {
                    oss << ",encoder=\"" << pinfo->encoder_cfg.codec << "\"";
                }
                // preproc: derive from engine options (global hint)
                std::string preproc = "cpu";
                auto eng = app.currentEngine();
                auto it = eng.options.find("use_cuda_preproc");
                if (it != eng.options.end()) {
                    std::string v = toLower(it->second);
                    if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
                }
                oss << ",preproc=\"" << preproc << "\"";
            }
            oss << "}";
            return oss.str();
        };

        // Per-pipeline FPS gauge
        out << "# HELP va_pipeline_fps Pipeline FPS per source\n";
        out << "# TYPE va_pipeline_fps gauge\n";
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            out << "va_pipeline_fps" << make_labels(info.stream_id, path, &info) << " " << info.metrics.fps << "\n";
        }

        // Per-pipeline frames processed/dropped with labels
        for (const auto& info : app.pipelines()) {
            const std::string path = classify_path(info);
            out << "va_frames_processed_total" << make_labels(info.stream_id, path, &info)
                << " " << static_cast<unsigned long long>(info.metrics.processed_frames) << "\n";
            out << "va_frames_dropped_total" << make_labels(info.stream_id, path, &info)
                << " " << static_cast<unsigned long long>(info.metrics.dropped_frames) << "\n";
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
            std::string base = make_labels(info.stream_id, path, &info);
            // prepend codec label
            auto with_codec = [&](const char* metric){
                std::ostringstream oss; oss << metric << "{source_id=\"" << info.stream_id << "\"";
                oss << ",path=\"" << path << "\"";
                if (ext_labels && !info.encoder_cfg.codec.empty()) oss << ",encoder=\"" << codec << "\"";
                if (ext_labels && !info.decoder_label.empty()) oss << ",decoder=\"" << info.decoder_label << "\"";
                // preproc
                if (ext_labels) {
                    std::string preproc = "cpu";
                    auto eng = app.currentEngine();
                    auto it = eng.options.find("use_cuda_preproc");
                    if (it != eng.options.end()) {
                        std::string v = toLower(it->second);
                        if (v=="1"||v=="true"||v=="yes"||v=="on") preproc = "cuda";
                    }
                    oss << ",preproc=\"" << preproc << "\"";
                }
                oss << "}"; return oss.str(); };

            out << with_codec("va_encoder_packets_total") << " "
                << static_cast<unsigned long long>(info.transport_stats.packets) << "\n";
            out << with_codec("va_encoder_bytes_total") << " "
                << static_cast<unsigned long long>(info.transport_stats.bytes) << "\n";
            out << with_codec("va_encoder_eagain_total") << " "
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

    HttpResponse handleLoggingGet(const HttpRequest& /*req*/) {
        auto& logger = va::core::Logger::instance();
        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        auto lvlToStr = [](va::core::LogLevel l){ switch(l){case va::core::LogLevel::Trace:return "trace";case va::core::LogLevel::Debug:return "debug";case va::core::LogLevel::Info:return "info";case va::core::LogLevel::Warn:return "warn";case va::core::LogLevel::Error:return "error";} return "info"; };
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

    HttpResponse handleMetricsConfigGet(const HttpRequest& /*req*/) {
        const auto& obs = app.appConfig().observability;
        const bool reg = metrics_registry_enabled_.has_value() ? *metrics_registry_enabled_ : obs.metrics_registry_enabled;
        const bool ext = metrics_extended_labels_.has_value() ? *metrics_extended_labels_ : obs.metrics_extended_labels;
        Json::Value payload = successPayload();
        Json::Value data(Json::objectValue);
        data["registry_enabled"] = reg;
        data["extended_labels"] = ext;
        payload["data"] = data;
        return jsonResponse(payload, 200);
    }

    HttpResponse handleMetricsConfigSet(const HttpRequest& req) {
        try {
            const Json::Value body = parseJson(req.body);
            if (body.isMember("registry_enabled")) { metrics_registry_enabled_ = body["registry_enabled"].asBool(); }
            if (body.isMember("extended_labels")) { metrics_extended_labels_ = body["extended_labels"].asBool(); }
            return handleMetricsConfigGet(req);
        } catch (const std::exception& ex) {
            return errorResponse(std::string("metrics set failed: ") + ex.what(), 400);
        }
    }

    // --- SSE helpers and streams ---
    static void sseSendAll(int fd, const std::string& s) {
#ifdef _WIN32
        send(fd, s.c_str(), static_cast<int>(s.size()), 0);
#else
        send(fd, s.c_str(), s.size(), 0);
#endif
    }
    static void sseWriteHeaders(int fd) {
        std::ostringstream hs;
        hs << "HTTP/1.1 200 OK\r\n";
        hs << "Content-Type: text/event-stream\r\n";
        hs << "Cache-Control: no-cache\r\n";
        hs << "Connection: keep-alive\r\n\r\n";
        sseSendAll(fd, hs.str());
    }
    static void sseEvent(int fd, const char* event, const Json::Value& data) {
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

    // Runtime metrics flags overrides (optional)
    std::optional<bool> metrics_registry_enabled_{};
    std::optional<bool> metrics_extended_labels_{};

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
                // Record Failed session attempt (best-effort)
                if (sessions_repo) {
                    std::string err; std::int64_t id = 0;
                    const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                    (void)sessions_repo->start(stream_id, profile, model_override.value_or(std::string()), uri, now_ms, &id, &err);
                    (void)sessions_repo->completeLatest(stream_id, profile, "Failed", app.lastError().empty()? std::string("subscribe failed") : app.lastError(), now_ms, &err);
                }
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
            // Sessions: start record
            if (sessions_repo) {
                std::string err; std::int64_t id = 0;
                const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                (void)sessions_repo->start(stream_id, profile, model_override.value_or(std::string()), uri, now_ms, &id, &err);
            }
            // DB: event + log
            emitEvent("info", "subscribe", profile, "rest", stream_id, std::string("uri=") + uri);
            emitLog("info", profile, "rest", stream_id, std::string("subscribe accepted: ") + *result);
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
            // Sessions: complete latest
            if (sessions_repo) {
                std::string err; const auto now_ms = static_cast<std::int64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::system_clock::now().time_since_epoch()).count());
                (void)sessions_repo->completeLatest(*stream_opt, *profile_opt, "Stopped", std::string(), now_ms, &err);
            }
            emitEvent("info", "unsubscribe", *profile_opt, "rest", *stream_opt, "ok");
            emitLog("info", *profile_opt, "rest", *stream_opt, "unsubscribe accepted");
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
            emitEvent("info", "switch_source", *profile_opt, "rest", *stream_opt, std::string("uri=") + *uri_opt);
            emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_source -> ") + *uri_opt);
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
            emitEvent("info", "switch_model", *profile_opt, "rest", *stream_opt, std::string("model=") + *model_opt);
            emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_model -> ") + *model_opt);
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
            emitEvent("info", "switch_task", *profile_opt, "rest", *stream_opt, std::string("task=") + *task_opt);
            emitLog("info", *profile_opt, "rest", *stream_opt, std::string("switch_task -> ") + *task_opt);
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
            emitEvent("info", "update_params", *profile_opt, "rest", *stream_opt, "params updated");
            emitLog("info", *profile_opt, "rest", *stream_opt, "params updated");
            return jsonResponse(payload, 200);
        } catch (const std::exception& ex) {
            return errorResponse(ex.what(), 400);
        }
    }

      HttpResponse handleSetEngine(const HttpRequest& req) {
          try {
              const Json::Value body = parseJson(req.body);
              // Log incoming request summary (do not dump entire body to avoid noise)
              try {
                  std::string t = body.isMember("type") && body["type"].isString() ? body["type"].asString() : "";
                  std::string p = body.isMember("provider") && body["provider"].isString() ? body["provider"].asString() : "";
                  int d = body.isMember("device") && body["device"].isInt() ? body["device"].asInt() : -1;
                  std::string opt_keys;
                  if (body.isMember("options") && body["options"].isObject()) {
                      const auto& opts = body["options"]; auto names = opts.getMemberNames();
                      for (size_t i=0;i<names.size();++i) { opt_keys += names[i]; if (i+1<names.size()) opt_keys += ","; }
                  }
                  VA_LOG_C(::va::core::LogLevel::Info, "rest")
                      << "engine.set called type='" << t << "' provider='" << p << "' device=" << d
                      << " option_keys=[" << opt_keys << "] (merge update)";
              } catch (...) { /* best-effort logging */ }
              // Merge semantics: start from current engine, override only provided fields
              auto current = app.currentEngine();
              va::core::EngineDescriptor desc = current;

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
                  concat += kv.second.id; concat += '|';
                  concat += kv.second.running ? '1' : '0'; concat += '|';
                  concat += std::to_string(static_cast<int>(kv.second.fps)); concat += ';';
              }
              uint64_t rev = std::hash<std::string>{}(concat);
              Json::Value items(Json::arrayValue);
              for (auto& kv : by_id) {
                  const auto& a = kv.second;
                  Json::Value node(Json::objectValue);
                  node["id"] = a.id; node["name"] = a.id; node["uri"] = a.uri; node["status"] = a.running ? "Running" : "Stopped"; node["fps"] = a.fps; items.append(node);
              }
              return std::make_pair(rev, items);
          };

          const uint64_t since = get_uint64("since", 0);
          { /* avoid Windows min/max macros issues by not using std::max here */ }
          int tmp_timeout = get_int("timeout_ms", 12000); if (tmp_timeout < 100) tmp_timeout = 100; const int timeout_ms = tmp_timeout;
          int tmp_interval = get_int("interval_ms", 300); if (tmp_interval < 80) tmp_interval = 80; const int interval_ms = tmp_interval;

          auto snap = snapshot();
          if (since == 0 || since != snap.first) {
              Json::Value payload = successPayload();
              Json::Value data(Json::objectValue);
              data["rev"] = static_cast<Json::UInt64>(snap.first);
              data["items"] = snap.second;
              payload["data"] = data;
              return jsonResponse(payload, 200);
          }
          // wait loop
          auto start = std::chrono::steady_clock::now();
          while (true) {
              std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms));
              auto cur = snapshot();
              if (cur.first != since) {
                  Json::Value payload = successPayload();
                  Json::Value data(Json::objectValue);
                  data["rev"] = static_cast<Json::UInt64>(cur.first);
                  data["items"] = cur.second;
                  payload["data"] = data;
                  return jsonResponse(payload, 200);
              }
              auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now() - start).count();
              if (elapsed >= timeout_ms) {
                  // keepalive payload with same rev, empty items to signal no-change
                  Json::Value payload = successPayload();
                  Json::Value data(Json::objectValue);
                  data["rev"] = static_cast<Json::UInt64>(since);
                  data["items"] = Json::arrayValue;
                  payload["data"] = data;
                  return jsonResponse(payload, 200);
              }
          }
      }

      // --- Observability: logs ---
      HttpResponse handleLogsRecent(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          std::string level = q.count("level") ? q["level"] : std::string();
          std::string stream_id = q.count("stream_id") ? q["stream_id"] : std::string();
          std::string node = q.count("node") ? q["node"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          const uint64_t from_ts = get_uint64("from_ts", 0);
          const uint64_t to_ts   = get_uint64("to_ts", 0);
          int limit = 200; if (auto it=q.find("limit"); it!=q.end()) { try { limit = std::stoi(it->second); } catch(...){} }
          // Try DB first if available
          if (logs_repo) {
              std::vector<va::storage::LogRow> rows; std::string err;
              if (logs_repo->listRecentFiltered(pipeline, level, stream_id, node, from_ts, to_ts, limit, &rows, &err)) {
                  Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
                  for (const auto& r : rows) {
                      Json::Value row(Json::objectValue);
                      row["ts"] = static_cast<Json::UInt64>(r.ts_ms);
                      row["level"] = r.level; if(!r.pipeline.empty()) row["pipeline"] = r.pipeline; if(!r.node.empty()) row["node"] = r.node; if(!r.stream_id.empty()) row["stream_id"] = r.stream_id; row["msg"] = r.message;
                      if(!r.extra_json.empty()) { Json::Value ej; try{ Json::CharReaderBuilder b; std::string errs; std::istringstream is(r.extra_json); Json::parseFromStream(b, is, &ej, &errs); }catch(...){ ej = Json::Value(Json::nullValue);} row["extra"] = ej; }
                      arr.append(row);
                  }
                  data["items"] = arr; payload["data"] = data; return jsonResponse(payload, 200);
              } else { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "rest", 5000) << "logs listRecentFiltered failed: " << err; }
          }
          // Fallback: synthesize lightweight rows from running pipelines
          Json::Value payload = successPayload();
          Json::Value arr(Json::arrayValue);
          int emitted = 0;
          auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL);
          for (const auto& info : app.pipelines()) {
              if (!info.running) continue;
              if (!pipeline.empty() && info.profile_id != pipeline) continue;
              Json::Value row(Json::objectValue);
              row["ts"] = now_ms;
              std::string lvl = level.empty()? std::string("Info") : level; row["level"] = lvl;
              row["pipeline"] = info.profile_id;
              row["node"] = "pipeline";
              row["msg"] = std::string("running fps=") + std::to_string(info.metrics.fps);
              arr.append(row);
              if (++emitted >= limit) break;
          }
          Json::Value data(Json::objectValue); data["items"] = arr; payload["data"] = data; return jsonResponse(payload, 200);
      }

      HttpResponse handleLogsWatch(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          std::string level = q.count("level") ? q["level"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
          auto fingerprint = [&](){ std::string key; key.reserve(128); for (const auto& p : app.pipelines()) { if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ':'; key += (p.running? '1':'0'); key += ';'; } if(!level.empty()){ key+="#"; key+=level; } return std::hash<std::string>{}(key); };
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

      // --- Observability: events ---
      HttpResponse handleEventsRecent(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          std::string level = q.count("level") ? q["level"] : std::string();
          std::string stream_id = q.count("stream_id") ? q["stream_id"] : std::string();
          std::string node = q.count("node") ? q["node"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          const uint64_t from_ts = get_uint64("from_ts", 0);
          const uint64_t to_ts   = get_uint64("to_ts", 0);
          int limit = 50; if (auto it=q.find("limit"); it!=q.end()) { try { limit = std::stoi(it->second); } catch(...){} }
          // Try DB first if available
          if (events_repo) {
              std::vector<va::storage::EventRow> rows; std::string err;
              if (events_repo->listRecentFiltered(pipeline, level, stream_id, node, from_ts, to_ts, limit, &rows, &err)) {
                  Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
                  for (const auto& r : rows) {
                      Json::Value e(Json::objectValue);
                      e["ts"] = static_cast<Json::UInt64>(r.ts_ms);
                      e["level"] = r.level; e["type"] = r.type; if(!r.pipeline.empty()) e["pipeline"] = r.pipeline; if(!r.node.empty()) e["node"] = r.node; if(!r.stream_id.empty()) e["stream_id"] = r.stream_id; e["msg"] = r.msg; if(!r.extra_json.empty()) { Json::Value ej; try{ Json::CharReaderBuilder b; std::string errs; std::istringstream is(r.extra_json); Json::parseFromStream(b, is, &ej, &errs); }catch(...){ ej = Json::Value(Json::nullValue);} e["extra"] = ej; }
                      arr.append(e);
                  }
                  data["items"] = arr; payload["data"] = data; return jsonResponse(payload, 200);
              } else { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "rest", 5000) << "events listRecentFiltered failed: " << err; }
          }
          // Fallback synthesized
          Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
          int emitted = 0; auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL);
          for (const auto& info : app.pipelines()) {
              if (!info.running) continue; if (!pipeline.empty() && info.profile_id != pipeline) continue;
              Json::Value e(Json::objectValue);
              e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level.empty()? "info" : level; e["type"] = e["level"]; e["msg"] = std::string("pipeline running packets=") + std::to_string(info.transport_stats.packets);
              arr.append(e); if (++emitted >= limit) break;
          }
          data["items"] = arr; payload["data"] = data; return jsonResponse(payload, 200);
      }
      
      // --- Database: health check ---
      HttpResponse handleDbPing(const HttpRequest&) {
          Json::Value payload;
          bool ok = false;
          std::string err;
          if (db_pool && db_pool->valid()) {
              ok = db_pool->ping(&err);
          } else {
              err = "database disabled";
          }
          payload["ok"] = ok;
          if (!ok && !err.empty()) payload["error"] = err;
          return jsonResponse(payload, ok ? 200 : 503);
      }

      HttpResponse handleDbPurge(const HttpRequest& req) {
          try {
              Json::Value body = parseJson(req.body);
              uint64_t events_sec = 0, logs_sec = 0;
              if (body.isMember("events_seconds") && body["events_seconds"].isUInt64()) events_sec = body["events_seconds"].asUInt64();
              if (body.isMember("logs_seconds") && body["logs_seconds"].isUInt64()) logs_sec = body["logs_seconds"].asUInt64();
              if (events_sec==0 && logs_sec==0) return errorResponse("missing events_seconds/logs_seconds", 400);
              Json::Value payload = successPayload(); Json::Value res(Json::objectValue);
              if (events_sec>0 && events_repo) { std::string err; bool ok = events_repo->purgeOlderThanSeconds(events_sec, &err); res["events_ok"] = ok; if(!ok) res["events_error"]=err; }
              if (logs_sec>0 && logs_repo)   { std::string err; bool ok = logs_repo->purgeOlderThanSeconds(logs_sec, &err);   res["logs_ok"] = ok;   if(!ok) res["logs_error"]=err; }
              payload["data"] = res; return jsonResponse(payload, 200);
          } catch (const std::exception& ex) {
              return errorResponse(ex.what(), 400);
          }
      }

      // --- Sessions: list with pagination/time-window ---
      HttpResponse handleSessionsList(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string stream = q.count("stream_id") ? q["stream_id"] : std::string();
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
          const uint64_t from_ts = get_uint64("from_ts", 0);
          const uint64_t to_ts   = get_uint64("to_ts", 0);
          int page = get_int("page", 1);
          int page_size = get_int("page_size", 0);
          int limit = get_int("limit", 50);
          if (page_size <= 0) page_size = limit > 0 ? limit : 50;

          if (sessions_repo) {
              std::vector<va::storage::SessionRow> rows; std::uint64_t total = 0; std::string err;
              if (sessions_repo->listRangePaginated(stream, pipeline, from_ts, to_ts, page, page_size, &rows, &total, &err)) {
                  Json::Value payload = successPayload(); Json::Value data(Json::objectValue); Json::Value arr(Json::arrayValue);
                  for (const auto& r : rows) {
                      Json::Value s(Json::objectValue);
                      s["id"] = static_cast<Json::UInt64>(r.id);
                      s["stream_id"] = r.stream_id; s["pipeline"] = r.pipeline; if(!r.model_id.empty()) s["model_id"] = r.model_id; s["status"] = r.status; if(!r.error_msg.empty()) s["error_msg"] = r.error_msg;
                      if (r.started_ms>0) s["started_at"] = static_cast<Json::UInt64>(r.started_ms);
                      if (r.stopped_ms>0) s["stopped_at"] = static_cast<Json::UInt64>(r.stopped_ms);
                      arr.append(s);
                  }
                  data["items"] = arr; data["total"] = static_cast<Json::UInt64>(total); payload["data"] = data; return jsonResponse(payload, 200);
              }
          }
          // Fallback: empty
          Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["items"] = Json::arrayValue; data["total"] = static_cast<Json::UInt64>(0); payload["data"] = data; return jsonResponse(payload, 200);
      }
      HttpResponse handleSessionsWatch(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string stream = q.count("stream_id") ? q["stream_id"] : std::string();
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
          const uint64_t since = get_uint64("since", 0);
          int tmp_to = get_int("timeout_ms", 12000); if (tmp_to < 100) tmp_to = 100; const int timeout_ms = tmp_to;
          int tmp_iv = get_int("interval_ms", 300);  if (tmp_iv < 80)  tmp_iv = 80;  const int interval_ms = tmp_iv;
          int limit = 50; if (auto it=q.find("limit"); it!=q.end()) { try { limit = std::stoi(it->second); } catch(...){} }
          auto fingerprint = [&](){ std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; if (!stream.empty() && p.stream_id != stream) continue; key += p.stream_id; key += ';'; } return std::hash<std::string>{}(key); };
          auto snapshot = [&](){ Json::Value items(Json::arrayValue); if (sessions_repo) { std::vector<va::storage::SessionRow> rows; std::string err; if (sessions_repo->listRecent(stream, pipeline, limit, &rows, &err)) { for (const auto& r : rows) { Json::Value s(Json::objectValue); s["id"] = static_cast<Json::UInt64>(r.id); s["stream_id"] = r.stream_id; s["pipeline"] = r.pipeline; if(!r.model_id.empty()) s["model_id"] = r.model_id; s["status"] = r.status; if(!r.error_msg.empty()) s["error_msg"] = r.error_msg; if (r.started_ms>0) s["started_at"] = static_cast<Json::UInt64>(r.started_ms); if (r.stopped_ms>0) s["stopped_at"] = static_cast<Json::UInt64>(r.stopped_ms); items.append(s); } } else { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "rest", 5000) << "sessions listRecent failed"; } } else { auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL); for (const auto& info : app.pipelines()) { if (!info.running) continue; if (!pipeline.empty() && info.profile_id != pipeline) continue; if (!stream.empty() && info.stream_id != stream) continue; Json::Value s(Json::objectValue); s["stream_id"] = info.stream_id; s["pipeline"] = info.profile_id; s["status"] = "Running"; s["started_at"] = now_ms; items.append(s); } } return items; };
          auto rev_now = fingerprint();
          if (!since || since != rev_now) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev_now); data["items"] = snapshot(); payload["data"] = data; return jsonResponse(payload, 200); }
          auto start = std::chrono::steady_clock::now();
          while (true) {
              std::this_thread::sleep_for(std::chrono::milliseconds(interval_ms)); auto cur = fingerprint();
              if (cur != since) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(cur); data["items"] = snapshot(); payload["data"] = data; return jsonResponse(payload, 200); }
              auto elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()-start).count();
              if (elapsed >= timeout_ms) { Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(since); data["items"] = Json::arrayValue; payload["data"] = data; return jsonResponse(payload, 200); }
          }
      }

      HttpResponse handleEventsWatch(const HttpRequest& req) {
          auto q = parseQueryKV(req.query);
          std::string pipeline = q.count("pipeline") ? q["pipeline"] : std::string();
          std::string level = q.count("level") ? q["level"] : std::string();
          auto get_uint64 = [&](const char* k, uint64_t def){ auto it=q.find(k); if(it==q.end()) return def; try { return static_cast<uint64_t>(std::stoull(it->second)); } catch(...) { return def; } };
          auto get_int = [&](const char* k, int def){ auto it=q.find(k); if(it==q.end()) return def; try { return std::stoi(it->second); } catch(...) { return def; } };
          auto fingerprint = [&](){ std::string key; key.reserve(64); for (const auto& p : app.pipelines()) { if (!p.running) continue; if (!pipeline.empty() && p.profile_id != pipeline) continue; key += p.stream_id; key += ';'; } if(!level.empty()){ key+="#"; key+=level; } return std::hash<std::string>{}(key); };
          const uint64_t since = get_uint64("since", 0);
          int tmp_to = get_int("timeout_ms", 12000); if (tmp_to < 100) tmp_to = 100; const int timeout_ms = tmp_to;
          int tmp_iv = get_int("interval_ms", 300);  if (tmp_iv < 80)  tmp_iv = 80;  const int interval_ms = tmp_iv;
          auto rev_now = fingerprint();
          if (!since || since != rev_now) {
              Json::Value payload = successPayload(); Json::Value data(Json::objectValue); data["rev"] = static_cast<Json::UInt64>(rev_now);
              Json::Value items(Json::arrayValue); auto now_ms = static_cast<Json::UInt64>(static_cast<uint64_t>(std::time(nullptr)) * 1000ULL);
              for (const auto& info : app.pipelines()) {
                  if (!info.running) continue; if (!pipeline.empty() && info.profile_id != pipeline) continue;
                  Json::Value e(Json::objectValue); e["ts"] = now_ms; e["pipeline"] = info.profile_id; e["level"] = level.empty()? "info" : level; e["type"] = e["level"]; e["msg"] = std::string("running bytes=") + std::to_string(info.transport_stats.bytes);
                  items.append(e);
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
