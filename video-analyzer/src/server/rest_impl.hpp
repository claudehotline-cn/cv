#pragma once
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
#include "core/wal.hpp"

#include "storage/db_pool.hpp"
#include "storage/log_repo.hpp"
#include "storage/event_repo.hpp"
#include "storage/session_repo.hpp"
#include "storage/graph_repo.hpp"
#include "storage/source_repo.hpp"
#include "media/whep_session.hpp"
#include "whep_control.grpc.pb.h"
#include "lro/runner.h"
#include "lro/state_store.h"
#include "lro/admission.h"

#include "control_plane_embedded/controllers/pipeline_controller.hpp"

#include <json/json.h>
#include "core/error_codes.hpp"
#include <yaml-cpp/yaml.h>
#if defined(USE_GRPC)
#include "source_control.grpc.pb.h"
#include <grpcpp/grpcpp.h>
#endif

#include <algorithm>
#include <atomic>
#include <cctype>
#include <cstddef>
#include <initializer_list>
#include <filesystem>
#include <map>
#include <unordered_set>
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
#include <deque>
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

namespace rest_detail {

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

} // namespace rest_detail

namespace {

using rest_detail::HttpRequest;
using rest_detail::HttpResponse;

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

        if (listen(server_socket_, 64) < 0) {
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

        // Apply per-connection recv/send timeouts to avoid long stalls (e.g., misbehaving clients)
#ifdef _WIN32
        {
            int to_ms = 4000; // 4s
            setsockopt(client_socket, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&to_ms), sizeof(to_ms));
            setsockopt(client_socket, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&to_ms), sizeof(to_ms));
        }
#endif

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

        // If headers not fully received (no CRLF CRLF), return 408 to prevent blocking
        if (request_data.find("\r\n\r\n") == std::string::npos) {
            HttpResponse response;
            response.status_code = 408; // Request Timeout
            Json::Value error(Json::objectValue);
            error["success"] = false;
            error["message"] = "request timeout while reading headers";
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
            StreamHandler stream_handler;
            std::map<std::string, std::string> sparams;
            {
                std::lock_guard<std::mutex> lock(routes_mutex_);
                for (auto& route : stream_routes_) {
                    std::map<std::string, std::string> params;
                    if (matchRoute(request.method, request.path, route, params)) {
                        sparams = std::move(params);
                        stream_handler = route.handler; // copy out of lock
                        matched_stream = true;
                        break;
                    }
                }
            }
            if (matched_stream) {
                request.params = std::move(sparams);
                try {
                    stream_handler(client_socket, request);
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
        bool expect_continue = false;
        for (const auto& entry : request.headers) {
            std::string header_name = toLower(entry.first);
            if (header_name == "content-length") {
                try {
                    content_length = static_cast<size_t>(std::stoll(entry.second));
                    has_content_length = true;
                } catch (...) {
                    content_length = 0;
                }
                continue;
            }
            if (header_name == "expect") {
                std::string v = toLower(entry.second);
                // Common pattern from clients like Postman when sending large bodies
                if (v.find("100-continue") != std::string::npos) expect_continue = true;
            }
        }

        if (has_content_length && request.body.size() < content_length) {
            if (expect_continue) {
                // Send 100-continue to prompt client to transmit the body
                const std::string cont = "HTTP/1.1 100 Continue\r\n\r\n";
                sendAll(client_socket, cont);
            }
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
        Handler normal_handler;
        std::map<std::string, std::string> nparams;
        {
            std::lock_guard<std::mutex> lock(routes_mutex_);
            for (auto& route : routes_) {
                std::map<std::string, std::string> params;
                if (matchRoute(request.method, request.path, route, params)) {
                    nparams = std::move(params);
                    normal_handler = route.handler; // copy out of lock
                    matched = true;
                    break;
                }
            }
        }
        if (matched) {
            request.params = std::move(nparams);
            try {
                response = normal_handler(request);
            } catch (const std::exception& ex) {
                Json::Value error;
                error["success"] = false;
                error["message"] = ex.what();
                response.status_code = 500;
                response.body = Json::writeString(Json::StreamWriterBuilder{}, error);
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

        // Read headers until an empty line after CRLF. We must trim trailing '\r' first
        // and break when the resulting line is empty. This avoids consuming the body as headers.
        while (std::getline(iss, line)) {
            if (!line.empty() && line.back() == '\r') {
                line.pop_back();
            }
            if (line.empty()) break;
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

static std::optional<std::pair<int,std::string>> http_post_json(const std::string& host, int port, const std::string& path, const std::string& json, int timeout_ms) {
#ifdef _WIN32
    SOCKET sock = INVALID_SOCKET;
    addrinfo hints{}; hints.ai_family = AF_INET; hints.ai_socktype = SOCK_STREAM; hints.ai_protocol = IPPROTO_TCP;
    addrinfo* result = nullptr;
    std::string port_str = std::to_string(port);
    if (getaddrinfo(host.c_str(), port_str.c_str(), &hints, &result) != 0 || !result) return std::nullopt;
    sock = socket(result->ai_family, result->ai_socktype, result->ai_protocol);
    if (sock == INVALID_SOCKET) { freeaddrinfo(result); return std::nullopt; }
    int to = timeout_ms; setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, reinterpret_cast<const char*>(&to), sizeof(to));
    setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, reinterpret_cast<const char*>(&to), sizeof(to));
    if (connect(sock, result->ai_addr, static_cast<int>(result->ai_addrlen)) == SOCKET_ERROR) { closesocket(sock); freeaddrinfo(result); return std::nullopt; }
    freeaddrinfo(result);
    std::ostringstream req;
    req << "POST " << path << " HTTP/1.1\r\n";
    req << "Host: " << host << "\r\n";
    req << "Content-Type: application/json\r\n";
    req << "Connection: close\r\n";
    req << "Content-Length: " << json.size() << "\r\n\r\n";
    req << json;
    std::string reqs = req.str();
    int sent = 0; while (sent < static_cast<int>(reqs.size())) {
        int n = send(sock, reqs.c_str() + sent, static_cast<int>(reqs.size()) - sent, 0);
        if (n <= 0) { closesocket(sock); return std::nullopt; }
        sent += n;
    }
    std::string resp; resp.reserve(4096); char buf[4096];
    for(;;){ int n = recv(sock, buf, sizeof(buf), 0); if (n <= 0) break; resp.append(buf, buf + n); }
    closesocket(sock);
    // parse status line
    int status = 0; {
        auto crlf = resp.find("\r\n"); if (crlf != std::string::npos) {
            std::string statusLine = resp.substr(0, crlf);
            auto sp = statusLine.find(' '); if (sp != std::string::npos) {
                auto sp2 = statusLine.find(' ', sp+1); if (sp2 != std::string::npos) {
                    try { status = std::stoi(statusLine.substr(sp+1, sp2-sp-1)); } catch(...) { status = 0; }
                }
            }
        }
    }
    auto pos = resp.find("\r\n\r\n"); std::string body = (pos==std::string::npos? std::string() : resp.substr(pos+4));
    return std::make_pair(status, body);
#else
    (void)host; (void)port; (void)path; (void)json; (void)timeout_ms; return std::nullopt;
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

#if defined(USE_GRPC)
  // --- VSM gRPC helpers ---
  static std::unique_ptr<vsm::v1::SourceControl::Stub> makeVsmStub(const std::string& addr) {
      grpc::ChannelArguments args; args.SetInt("grpc.keepalive_time_ms", 30000); args.SetInt("grpc.keepalive_timeout_ms", 10000);
      auto ch = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
      return vsm::v1::SourceControl::NewStub(ch);
  }
  static bool vsmGrpcAttach(const std::string& addr, const std::string& id, const std::string& uri,
                            const std::string& profile, const std::string& model, std::string* err) {
      try {
          auto stub = makeVsmStub(addr);
          grpc::ClientContext ctx; auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(8000); ctx.set_deadline(ddl);
          vsm::v1::AttachRequest req; req.set_attach_id(id); req.set_source_uri(uri); if (!profile.empty()) (*req.mutable_options())["profile"] = profile; if (!model.empty()) (*req.mutable_options())["model_id"] = model;
          vsm::v1::AttachReply rep; auto st = stub->Attach(&ctx, req, &rep);
          if (!st.ok()) { if (err) *err = st.error_message(); return false; }
          return true;
      } catch (const std::exception& ex) { if (err) *err = ex.what(); return false; }
  }
  static bool vsmGrpcDetach(const std::string& addr, const std::string& id, std::string* err) {
      try {
          auto stub = makeVsmStub(addr);
          grpc::ClientContext ctx; auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(8000); ctx.set_deadline(ddl);
          vsm::v1::DetachRequest req; req.set_attach_id(id); vsm::v1::DetachReply rep; auto st = stub->Detach(&ctx, req, &rep);
          if (!st.ok()) { if (err) *err = st.error_message(); return false; }
          return true;
      } catch (const std::exception& ex) { if (err) *err = ex.what(); return false; }
  }
#endif

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

} // namespace rest_detail

using namespace rest_detail;

struct RestServer::Impl {
    RestServerOptions options;
    va::app::Application& app;
    SimpleHttpServer server;
    // Optional DB-backed storage
    std::shared_ptr<va::storage::DbPool> db_pool;
    std::unique_ptr<va::storage::LogRepo> logs_repo;
    std::unique_ptr<va::storage::EventRepo> events_repo;
    std::unique_ptr<va::storage::SessionRepo> sessions_repo;
    std::unique_ptr<va::storage::GraphRepo> graphs_repo;
    std::unique_ptr<va::storage::SourceRepo> sources_repo;
    // Legacy SubscriptionManager removed; runner + admission are the source of truth
    int cfg_heavy_slots_{0};
    int cfg_model_slots_{0};
    int cfg_rtsp_slots_{0};
    size_t cfg_max_queue_{0};
    int cfg_ttl_seconds_{0};
    int cfg_open_rtsp_slots_{0};
    int cfg_start_pipeline_slots_{0};
    // Subscriptions 配置来源回显
    std::string subs_src_heavy {"defaults"};
    std::string subs_src_model {"defaults"};
    std::string subs_src_rtsp  {"defaults"};
    std::string subs_src_queue {"defaults"};
    std::string subs_src_ttl   {"defaults"};
    std::string subs_src_open_rtsp {"defaults"};
    std::string subs_src_start_pipeline {"defaults"};

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
    // Retention metrics
    std::atomic<std::uint64_t> retention_runs_total{0};
    std::atomic<std::uint64_t> retention_failures_total{0};
    std::atomic<std::uint64_t> retention_last_ms{0};

    // Control-plane request metrics (op: apply/apply_batch/hotswap/drain/remove)
    std::mutex cp_mu;
    std::unordered_map<std::string, std::unordered_map<std::string, std::uint64_t>> cp_totals_by_code; // op -> code -> total
    std::unordered_map<std::string, std::vector<std::uint64_t>> cp_hist_buckets; // op -> buckets
    std::unordered_map<std::string, double> cp_hist_sum; // seconds sum per op
    std::unordered_map<std::string, std::uint64_t> cp_hist_count;
    const std::vector<double> cp_bounds {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};

    // Quotas/rate limiting (per key, best-effort)
    std::mutex quota_mu_;
    std::unordered_map<std::string, std::deque<std::uint64_t>> quota_hits_by_key_ms_;
    std::atomic<std::uint64_t> quota_drop_global_concurrent_{0};
    std::atomic<std::uint64_t> quota_drop_key_concurrent_{0};
    std::atomic<std::uint64_t> quota_drop_key_rate_{0};
    std::atomic<std::uint64_t> quota_drop_acl_scheme_{0};
    std::atomic<std::uint64_t> quota_drop_acl_profile_{0};
    // Observe-only counts (no enforcement)
    std::atomic<std::uint64_t> quota_would_drop_global_concurrent_{0};
    std::atomic<std::uint64_t> quota_would_drop_key_concurrent_{0};
    std::atomic<std::uint64_t> quota_would_drop_key_rate_{0};
    std::atomic<std::uint64_t> quota_would_drop_acl_scheme_{0};
    std::atomic<std::uint64_t> quota_would_drop_acl_profile_{0};

    std::optional<bool> metrics_registry_enabled_{};
    std::optional<bool> metrics_extended_labels_{};

    void recordCpMetric(const std::string& op, int http_status, const std::chrono::steady_clock::time_point& t0);
    static std::uint64_t now_ms();

    void startDbWorker();
    void stopDbWorker();
    void startRetentionWorker();
    void stopRetentionWorker();

    void emitEvent(const std::string& level,
                   const std::string& type,
                   const std::string& pipeline,
                   const std::string& node,
                   const std::string& stream_id,
                   const std::string& msg,
                   const std::string& extra_json = std::string());

    void emitLog(const std::string& level,
                 const std::string& pipeline,
                 const std::string& node,
                 const std::string& stream_id,
                 const std::string& message,
                 const std::string& extra_json = std::string());

    Impl(RestServerOptions opts, va::app::Application& application);
    ~Impl();

    void registerRoutes();

    bool start();
    void stop();

    // Control-plane APIs
    HttpResponse handleCpApply(const HttpRequest& req);
    HttpResponse handleCpApplyBatch(const HttpRequest& req);
    HttpResponse handleCpHotSwap(const HttpRequest& req);
    HttpResponse handleCpRemove(const HttpRequest& req);
    HttpResponse handleOrchAttachApply(const HttpRequest& req);
    HttpResponse handleOrchDetachRemove(const HttpRequest& req);
    HttpResponse handleOrchHealth(const HttpRequest& req);
    HttpResponse handleCpStatus(const HttpRequest& req);
    HttpResponse handleCpDrain(const HttpRequest& req);

    // System information and graphs
    HttpResponse handleSystemInfo(const HttpRequest& req);
    static std::vector<std::filesystem::path> graphDirCandidates();
    HttpResponse handleGraphsList(const HttpRequest& req);
    HttpResponse handleGraphSwitch(const HttpRequest& req);
    HttpResponse handlePreflight(const HttpRequest& req);
    HttpResponse handleSystemStats(const HttpRequest& req);

    // Metrics endpoints
    HttpResponse handleMetrics(const HttpRequest& req);
    HttpResponse handleMetricsConfigGet(const HttpRequest& req);
    HttpResponse handleMetricsConfigSet(const HttpRequest& req);

    // Admin: WAL evidence (read-only)
    HttpResponse handleWalSummary(const HttpRequest& req);
    HttpResponse handleWalTail(const HttpRequest& req);

    // Logging and SSE utilities
    static va::core::LogLevel parseLevelStr(const std::string& s);
    HttpResponse handleLoggingGet(const HttpRequest& req);
    HttpResponse handleLoggingSet(const HttpRequest& req);

    static void sseSendAll(int fd, const std::string& s);
    static void sseWriteHeaders(int fd);
    static void sseEvent(int fd, const char* event, const Json::Value& data);
    static void sseEventWithId(int fd, const char* event, const Json::Value& data, std::uint64_t id, int retry_ms);
    static void sseKeepAlive(int fd);

    void streamSubscriptionSSE(int fd, const HttpRequest& req, const std::string& id);
    void streamSourcesSSE(int fd, const HttpRequest& req);
    void streamLogsSSE(int fd, const HttpRequest& req);
    void streamEventsSSE(int fd, const HttpRequest& req);

    // Catalog endpoints
    HttpResponse handleModels(const HttpRequest& req);
    HttpResponse handleProfiles(const HttpRequest& req);
    HttpResponse handlePipelines(const HttpRequest& req);

    // Subscription and pipeline management
    HttpResponse handleSubscriptionCreate(const HttpRequest& req);
    HttpResponse handleSubscriptionGet(const HttpRequest& req, const std::string& id);
    HttpResponse handleSubscriptionDelete(const HttpRequest& req, const std::string& id);
    HttpResponse handleSubscribe(const HttpRequest& req);
    HttpResponse handleUnsubscribe(const HttpRequest& req);
    HttpResponse handleSourceSwitch(const HttpRequest& req);
    HttpResponse handleModelSwitch(const HttpRequest& req);
    HttpResponse handleTaskSwitch(const HttpRequest& req);
    HttpResponse handleParamsUpdate(const HttpRequest& req);
    HttpResponse handleSetEngine(const HttpRequest& req);

    // Sources overview
    HttpResponse handleSources(const HttpRequest& req);
    HttpResponse handleSourcesWatch(const HttpRequest& req);

    // Logs and events endpoints
    HttpResponse handleLogsRecent(const HttpRequest& req);
    HttpResponse handleLogsWatch(const HttpRequest& req);
    HttpResponse handleEventsRecent(const HttpRequest& req);

    // Database utilities
    HttpResponse handleDbPing(const HttpRequest& req);
    HttpResponse handleDbPurge(const HttpRequest& req);
    HttpResponse handleDbRetentionStatus(const HttpRequest& req);

    // Sessions endpoints
    HttpResponse handleSessionsList(const HttpRequest& req);
    HttpResponse handleSessionsWatch(const HttpRequest& req);
    HttpResponse handleEventsWatch(const HttpRequest& req);

    // WHEP control
    HttpResponse handleWhepCors(const HttpRequest& req);
    std::mutex whep_mu_;
    std::unordered_map<std::string, std::pair<std::string,std::string>> whep_map_;
    static std::vector<std::string> parseHosts(const char* envName);
    static std::string pickHost(const std::vector<std::string>& hosts, const std::string& key);
    static std::unique_ptr<va::whep::WhepControl::Stub> makeWhepStub(const std::string& addr);
    static bool grpcWhepAdd(const std::string& addr, const std::string& stream, const std::string& offer, std::string* sid, std::string* answer);
    static bool grpcWhepPatch(const std::string& addr, const std::string& sid, const std::string& frag);
    static bool grpcWhepDel(const std::string& addr, const std::string& sid);
    static std::string genCpSid();
    HttpResponse handleWhepCreate(const HttpRequest& req);
    HttpResponse handleWhepPatch(const HttpRequest& req);
    HttpResponse handleWhepDelete(const HttpRequest& req);

    // LRO (Long-Running Operation) optional runner (feature-flagged)
    bool lro_enabled_{false};
    std::unique_ptr<lro::Runner> lro_runner_;
    std::shared_ptr<lro::IStateStore> lro_store_;
    std::unique_ptr<lro::AdmissionPolicy> lro_admission_;

    // WAL bookkeeping to avoid duplicate terminal appends (best-effort only)
    std::mutex wal_mu_;
    std::unordered_set<std::string> wal_appended_ids_;
};

} // namespace va::server

            
