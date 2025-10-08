#include "media/transport_webrtc_datachannel.hpp"

#include "core/logger.hpp"

#include <ixwebsocket/IXWebSocketServer.h>
#include <json/json.h>
#include <rtc/rtc.hpp>
#include <rtc/h264rtppacketizer.hpp>
#include <rtc/pacinghandler.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <cstddef>
#include <cstring>
#include <functional>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include "core/drop_metrics.hpp"
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

// Forward declare helper used later in this TU
static inline void ensure_annexb(std::vector<uint8_t>& buf);

namespace va::media {

namespace {

constexpr uint16_t kDefaultSignalingPort = 8083;
constexpr uint16_t kDefaultStreamerPort = 8080;
constexpr char kDefaultEndpoint[] = "ws://127.0.0.1:8083";

// Forward declare helper implemented later in this TU (same namespace scope)
static inline void maybe_inject_param_sets(std::vector<uint8_t>& frame);

// 将长文本截断到 max_len，便于日志安全输出
std::string truncate_for_log(const std::string& s, size_t max_len = 1024) {
    if (s.size() <= max_len) return s;
    std::ostringstream oss;
    oss << s.substr(0, max_len) << "... (" << (s.size() - max_len) << " bytes truncated)";
    return oss.str();
}

// 将 JSON 值转为字符串（用于日志）并截断
std::string json_to_string_trunc(const Json::Value& v, size_t max_len = 1024) {
    Json::StreamWriterBuilder b;
    std::string s = Json::writeString(b, v);
    return truncate_for_log(s, max_len);
}

uint16_t parsePort(const std::string& endpoint) {
    auto pos = endpoint.rfind(':');
    if (pos == std::string::npos) {
        return kDefaultSignalingPort;
    }
    std::string tail = endpoint.substr(pos + 1);
    auto slash = tail.find_first_of("/\\");
    if (slash != std::string::npos) {
        tail = tail.substr(0, slash);
    }
    try {
        int value = std::stoi(tail);
        if (value > 0 && value <= 65535) {
            return static_cast<uint16_t>(value);
        }
    } catch (...) {
    }
    return kDefaultSignalingPort;
}

std::string sanitizeTrackId(const std::string& input) {
    if (!input.empty()) {
        return input;
    }
    return std::string("stream_default");
}

// 测试开关：是否允许发送线程在所请求源没有帧时，改为“有帧就取”。
// 通过环境变量 VA_TEST_SEND_ANY_FRAME 控制，缺省启用（true），便于联调。
static bool kTestSendAnyFrame = []() {
    const char* v = std::getenv("VA_TEST_SEND_ANY_FRAME");
    if (!v) return true; // 默认开启，便于测试
    std::string s(v);
    for (auto& c : s) c = (char)std::tolower(c);
    return (s == "1" || s == "true" || s == "yes" || s == "on");
}();

class SignalingServer {
public:
    SignalingServer() = default;
    ~SignalingServer() {
        stop();
    }

    bool start(uint16_t port) {
        if (running_) {
            return true;
        }
        try {
            port_ = port;
            server_ = std::make_unique<ix::WebSocketServer>(port);
            server_->setOnConnectionCallback(
                [this](std::weak_ptr<ix::WebSocket> webSocket, std::shared_ptr<ix::ConnectionState> state) {
                    onConnection(webSocket, state);
                    if (auto shared_ws = webSocket.lock()) {
                        shared_ws->setOnMessageCallback(
                            [this, webSocket, state](const ix::WebSocketMessagePtr& msg) {
                                if (auto shared_ws = webSocket.lock()) {
                                    onMessage(state, *shared_ws, msg);
                                }
                            }
                        );
                    }
                }
            );

            auto result = server_->listen();
            if (!result.first) {
                VA_LOG_ERROR() << "Signaling listen failed on port " << port << ": " << result.second;
                return false;
            }

            server_->start();
            running_ = true;
            VA_LOG_INFO() << "WebRTC signaling server started on port " << port;
            return true;
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "Failed to start signaling server: " << ex.what();
            return false;
        }
    }

    void stop() {
        if (!running_) {
            return;
        }
        running_ = false;
        try {
            if (server_) {
                server_->stop();
                server_.reset();
            }
            std::scoped_lock lock(clients_mutex_);
            clients_.clear();
            connection_to_client_.clear();
            VA_LOG_INFO() << "WebRTC signaling server stopped";
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "Error stopping signaling server: " << ex.what();
        }
    }

    void setMessageCallback(std::function<void(const std::string&, const Json::Value&)> callback) {
        message_callback_ = std::move(callback);
    }

    bool sendToClient(const std::string& client_id, const Json::Value& message) {
        std::scoped_lock lock(clients_mutex_);
        auto it = clients_.find(client_id);
        if (it == clients_.end()) {
            return false;
        }
        const std::string t = message.get("type", "").asString();
        VA_LOG_DEBUG() << "[Signaling] send type='" << t << "' to client=" << client_id
                        << ", payload=" << json_to_string_trunc(message, 1024);
        sendMessage(it->second.connection, message);
        return true;
    }

private:
    void onConnection(std::weak_ptr<ix::WebSocket> webSocket, std::shared_ptr<ix::ConnectionState> connectionState) {
        VA_LOG_INFO() << "Signaling client connected from " << connectionState->getRemoteIp();

        Json::Value welcome;
        welcome["type"] = "welcome";
        welcome["message"] = "Please send authentication info";
        welcome["timestamp"] = static_cast<Json::Int64>(std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count());
        sendMessage(webSocket, welcome);
    }

    void onMessage(std::shared_ptr<ix::ConnectionState> /*state*/, ix::WebSocket& webSocket, const ix::WebSocketMessagePtr& msg) {
        if (msg->type == ix::WebSocketMessageType::Message) {
            try {
                Json::Value json_msg;
                Json::CharReaderBuilder builder;
                std::string errs;
                std::istringstream iss(msg->str);
                if (!Json::parseFromStream(builder, iss, &json_msg, &errs)) {
                    VA_LOG_ERROR() << "JSON parse error: " << errs;
                    VA_LOG_DEBUG() << "Raw signaling payload: " << msg->str;
                    return;
                }

                const std::string msg_type = json_msg.get("type", "").asString();
                VA_LOG_DEBUG() << "[Signaling] inbound type='" << msg_type << "' size=" << msg->str.size()
                                << ", payload=" << truncate_for_log(msg->str, 1024);
                if (msg_type == "auth") {
                    auto clients = server_->getClients();
                    for (auto client : clients) {
                        if (client.get() == &webSocket) {
                            handleClientAuthentication(std::weak_ptr<ix::WebSocket>(client), json_msg);
                            break;
                        }
                    }
                } else if (kTestSendAnyFrame) {
                    // Find client_id under lock, then invoke callback outside to avoid deadlocks
                    std::string client_id;
                    {
                        std::scoped_lock lock(clients_mutex_);
                        for (auto& [weak_ws, cid] : connection_to_client_) {
                            if (auto shared_ws = weak_ws.lock()) {
                                if (shared_ws.get() == &webSocket) {
                                    client_id = cid;
                                    break;
                                }
                            }
                        }
                    }
                    if (!client_id.empty() && message_callback_) {
                        VA_LOG_DEBUG() << "[Signaling] dispatch type='" << msg_type << "' to client=" << client_id;
                        message_callback_(client_id, json_msg);
                    }
                }
            } catch (const std::exception& ex) {
                VA_LOG_ERROR() << "Signaling handling error: " << ex.what();
            }
        } else if (msg->type == ix::WebSocketMessageType::Close) {
            std::scoped_lock lock(clients_mutex_);
            for (auto it = connection_to_client_.begin(); it != connection_to_client_.end();) {
                if (auto shared_ws = it->first.lock()) {
                    if (shared_ws.get() == &webSocket) {
                        std::string client_id = it->second;
                        clients_.erase(client_id);
                        it = connection_to_client_.erase(it);
                        break;
                    } else {
                        ++it;
                    }
                } else {
                    it = connection_to_client_.erase(it);
                }
            }
        }
    }

    void handleClientAuthentication(std::weak_ptr<ix::WebSocket> webSocket, const Json::Value& message) {
        std::string client_type = message.get("client_type", "").asString();
        if (client_type.empty() && message.isMember("data")) {
            client_type = message["data"].get("client_type", "").asString();
        }

        if (client_type.empty()) {
            Json::Value error;
            error["type"] = "auth_error";
            error["message"] = "Missing client_type";
            sendMessage(webSocket, error);
            return;
        }

        std::string client_id = generateClientId();

        std::scoped_lock lock(clients_mutex_);

        ClientInfo info;
        info.connection = webSocket;
        info.client_id = client_id;
        info.client_type = client_type;
        info.connect_time = std::chrono::duration_cast<std::chrono::seconds>(
            std::chrono::system_clock::now().time_since_epoch()).count();
        info.authenticated = true;

        clients_[client_id] = info;
        connection_to_client_[webSocket] = client_id;

        Json::Value response;
        response["type"] = "auth_success";
        response["client_id"] = client_id;
        response["message"] = "Authentication successful";
        VA_LOG_INFO() << "[Signaling] auth_success client_id=" << client_id << " type=" << client_type;
        sendMessage(webSocket, response);
    }

    void sendMessage(std::weak_ptr<ix::WebSocket> webSocket, const Json::Value& message) {
        if (auto shared_ws = webSocket.lock()) {
            try {
                Json::StreamWriterBuilder builder;
                std::string json_str = Json::writeString(builder, message);
                shared_ws->send(json_str);
            } catch (const std::exception& ex) {
                VA_LOG_ERROR() << "Error sending signaling message: " << ex.what();
            }
        }
    }

    std::string generateClientId() {
        static std::random_device rd;
        static std::mt19937 gen(rd());
        static std::uniform_int_distribution<> dis(100000, 999999);
        return "client_" + std::to_string(dis(gen));
    }

    struct ClientInfo {
        std::weak_ptr<ix::WebSocket> connection;
        std::string client_id;
        std::string client_type;
        int64_t connect_time;
        bool authenticated;
    };

    std::unique_ptr<ix::WebSocketServer> server_;
    std::atomic<bool> running_{false};
    uint16_t port_{0};
    mutable std::mutex clients_mutex_;
    std::map<std::string, ClientInfo> clients_;
    std::map<std::weak_ptr<ix::WebSocket>, std::string, std::owner_less<std::weak_ptr<ix::WebSocket>>> connection_to_client_;
    std::function<void(const std::string&, const Json::Value&)> message_callback_;
};

class WebRTCVideoSource {
public:
    WebRTCVideoSource() = default;

    void PushEncodedFrame(const std::string& source_id, std::vector<uint8_t>&& data) {
        if (data.empty()) {
            return;
        }
        std::scoped_lock lock(mutex_);
        auto& queue = frames_[source_id];
        queue.push(std::move(data));
        size_t dropped = 0;
        while (queue.size() > 10) {
            queue.pop();
            ++dropped;
        }
        if (dropped > 0) {
            va::core::DropMetrics::increment(source_id, va::core::DropMetrics::Reason::QueueOverflow, static_cast<uint64_t>(dropped));
        }
        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 1000)
            << "queued frame for source='" << source_id << "' size=" << queue.size();
    }

    bool HasEncodedFrame(const std::string& source_id) const {
        std::scoped_lock lock(mutex_);
        auto it = frames_.find(source_id);
        bool ok = it != frames_.end() && !it->second.empty();
        if (!ok) {
            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 1000)
                << "no frame available for source='" << source_id << "'";
        }
        return ok;
    }

    std::vector<uint8_t> GetEncodedFrame(const std::string& source_id) {
        std::scoped_lock lock(mutex_);
        auto it = frames_.find(source_id);
        if (it == frames_.end() || it->second.empty()) {
            return {};
        }
        std::vector<uint8_t> data = std::move(it->second.front());
        it->second.pop();
        return data;
    }

    // 测试辅助：从任意有帧的队列弹出一帧
    bool TryGetAnyEncodedFrame(std::string& out_source_id, std::vector<uint8_t>& out_data) {
        std::scoped_lock lock(mutex_);
        for (auto it = frames_.begin(); it != frames_.end(); ++it) {
            if (!it->second.empty()) {
                out_source_id = it->first;
                out_data = std::move(it->second.front());
                it->second.pop();
                return true;
            }
        }
        return false;
    }

private:
    mutable std::mutex mutex_;
    std::map<std::string, std::queue<std::vector<uint8_t>>> frames_;
};

class WebRTCStreamer {
public:
    WebRTCStreamer()
        : initialized_(false), port_(0), should_stop_sender_(false) {
        video_source_ = std::make_unique<WebRTCVideoSource>();
    }

    ~WebRTCStreamer() {
        Shutdown();
    }

    bool Initialize(int port) {
        if (initialized_) {
            return true;
        }
        try {
            port_ = port;
            // 本机联调缺省：仅 UDP，不使用 STUN，仅 host 候选
            auto parse_bool_env = [](const char* name, bool defval) {
                const char* v = std::getenv(name);
                if (!v) return defval;
                std::string s(v);
                for (auto& c : s) c = (char)std::tolower(c);
                return (s=="1"||s=="true"||s=="yes"||s=="on");
            };

            rtc_config_.enableIceTcp = parse_bool_env("VA_ICE_TCP", true); // 默认 UDP-only
            rtc_config_.iceServers.clear();
            VA_LOG_INFO() << "[WebRTC] Configuration: enableIceTcp=" << (rtc_config_.enableIceTcp?"true":"false")
                          << ", iceServers=" << rtc_config_.iceServers.size();
            for (const auto& s : rtc_config_.iceServers) {
                VA_LOG_INFO() << "[WebRTC] iceServer: host='" << s.hostname << "' port=" << s.port << " user='" << s.username << "'";
            }
            rtc_config_.disableAutoNegotiation = false;
            rtc_config_.portRangeBegin = 10000;
            rtc_config_.portRangeEnd = 10100;

            // RTP/发送节奏可在环境变量控制（不改动对外接口）
            mtu_ = 1200; // 默认安全值
            if (const char* m = std::getenv("VA_WEBRTC_MTU")) {
                try { size_t v = static_cast<size_t>(std::stoul(m)); if (v >= 400 && v <= 1500) mtu_ = v; } catch (...) {}
            }
            pace_bps_ = 0; // 0=关闭；UINT_MAX=auto
            if (const char* p = std::getenv("VA_WEBRTC_PACE")) {
                auto toLower = [](std::string s){ for (auto& c : s) c = (char)std::tolower(c); return s; };
                std::string t = toLower(std::string(p));
                if (t == "off" || t == "0" || t == "none") pace_bps_ = 0;
                else if (t == "auto") pace_bps_ = UINT_MAX;
                else {
                    unsigned long val = 0; size_t i = 0; while (i < t.size() && std::isdigit((unsigned char)t[i])) { val = val*10 + (t[i]-'0'); ++i; }
                    if (i < t.size()) { if (t[i] == 'k') val *= 1000ul; else if (t[i] == 'm') val *= 1000ul * 1000ul; }
                    pace_bps_ = static_cast<unsigned>(val);
                }
            }
            fps_ = 30; // 目标 FPS（用于 RTP ts 与发送调度）
            if (const char* f = std::getenv("VA_WEBRTC_FPS")) { try { int v = std::stoi(f); if (v >= 5 && v <= 120) fps_ = v; } catch (...) {} }
            // A-2: 不指定环回，使用系统可用的本机/内网地址做 host 候选；可通过 VA_ICE_BIND 覆盖
            if (const char* bind = std::getenv("VA_ICE_BIND")) {
                rtc_config_.bindAddress = std::string(bind);
            } else {
                // 显式绑定到指定网卡（用户要求 192.168.50.183）
                rtc_config_.bindAddress = std::nullopt;
            }

            should_stop_sender_ = false;
            video_sender_thread_ = std::thread(&WebRTCStreamer::SendVideoFrames, this);

            initialized_ = true;
            VA_LOG_INFO() << "WebRTC streamer initialized on port " << port;
            VA_LOG_INFO() << "[WebRTC] ICE config: udp-only=" << std::boolalpha << (!rtc_config_.enableIceTcp)
                          << ", bindAddress=" << (rtc_config_.bindAddress ? *rtc_config_.bindAddress : std::string("<any>"))
                          << ", portRange=" << rtc_config_.portRangeBegin << "-" << rtc_config_.portRangeEnd
                          << ", iceServers=" << rtc_config_.iceServers.size();
            return true;
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "WebRTC streamer initialization failed: " << ex.what();
            return false;
        }
    }

    void Shutdown() {
        if (!initialized_) {
            return;
        }
        should_stop_sender_ = true;
        if (video_sender_thread_.joinable()) {
            video_sender_thread_.join();
        }
        std::scoped_lock lock(clients_mutex_);
        clients_.clear();
        initialized_ = false;
        VA_LOG_INFO() << "WebRTC streamer shut down";
    }

    bool CreateOffer(const std::string& client_id, std::string& sdp_offer) {
        if (!initialized_) {
            return false;
        }

        try {
            auto peer_connection = CreatePeerConnection(client_id);
            if (!peer_connection) {
                return false;
            }

            auto client = std::make_unique<ClientConnection>();
            client->client_id = client_id;
            client->peer_connection = peer_connection;
            client->connected = false;
            client->requested_source = "camera_01";
            // generate SSRC
            client->ssrc = std::random_device{}();

            // 仅添加视频轨（H264），暂不创建 DataChannel，避免 m=video 被禁用导致的 BUNDLE 异常
            try {
                rtc::Description::Video vdesc("video");
                vdesc.setDirection(rtc::Description::Direction::SendOnly);
                vdesc.addH264Codec(96, rtc::DEFAULT_H264_VIDEO_PROFILE);
                // set SSRC and msid/cname to stabilize SDP
                vdesc.addSSRC(client->ssrc, std::string("va"), std::string("stream1"), std::string("video1"));
                VA_LOG_INFO() << "[WebRTC] adding video track mid='video' codec=H264 pt=96 ssrc=" << client->ssrc << " for client " << client_id;
                client->video_track = peer_connection->addTrack(vdesc);
                            attachMediaHandlers(client->video_track, client->ssrc);
                // 附加 H.264 RTP 打包器，确保包化配置稳定
                // 默认媒体处理器足够，FrameInfo.payloadType=96
            } catch (const std::exception& ex) {
                VA_LOG_ERROR() << "Failed to add H264 video track: " << ex.what();
            }

            {
                std::scoped_lock lock(clients_mutex_);
                clients_[client_id] = std::move(client);
            }

            VA_LOG_INFO() << "[WebRTC] creating SDP offer for client " << client_id;
            auto offer_desc = peer_connection->createOffer();

            // 等待 onLocalDescription 回调返回的最终 SDP（包含正确的 m-lines 与 ICE 属性）
            std::string final_sdp;
            std::mutex ldesc_mtx;
            std::condition_variable ldesc_cv;
            bool ldesc_ready = false;
            peer_connection->onLocalDescription([&](rtc::Description desc) {
                {
                    std::lock_guard<std::mutex> lk(ldesc_mtx);
                    final_sdp = std::string(desc);
                    ldesc_ready = true;
                }
                ldesc_cv.notify_one();
                VA_LOG_DEBUG() << "[WebRTC] onLocalDescription ready for client " << client_id
                               << ", type=" << desc.typeString() << ", size=" << final_sdp.size();
            });

            peer_connection->setLocalDescription(rtc::Description::Type::Offer);

            {
                std::unique_lock<std::mutex> lk(ldesc_mtx);
                ldesc_cv.wait_for(lk, std::chrono::milliseconds(1500), [&]{ return ldesc_ready; });
            }
            sdp_offer = ldesc_ready ? final_sdp : std::string(offer_desc);
            // 补丁：修正 m=video 端口为 9（部分环境下 libdatachannel 会给出 port 0 导致浏览器禁用 m-line）
            {
                const std::string needle = "m=video 0 UDP/TLS/RTP/SAVPF";
                const std::string repl   = "m=video 9 UDP/TLS/RTP/SAVPF";
                auto pos = sdp_offer.find(needle);
                if (pos != std::string::npos) {
                    sdp_offer.replace(pos, needle.size(), repl);
                    VA_LOG_WARN() << "[WebRTC] patched offer SDP: set m=video port to 9 (workaround)";
                }
            }
            const bool has_h264 = sdp_offer.find("H264/90000") != std::string::npos;
            const bool has_fmtp = sdp_offer.find("packetization-mode=1") != std::string::npos;
            VA_LOG_DEBUG() << "[WebRTC] offer SDP size=" << sdp_offer.size() << " h264=" << has_h264 << " fmtp=" << has_fmtp;
            VA_LOG_DEBUG() << "[WebRTC] offer SDP (trunc):\n" << truncate_for_log(sdp_offer, 2048);
            return true;
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "Failed to create offer for client " << client_id << ": " << ex.what();
            return false;
        }
    }

    bool HandleAnswer(const std::string& client_id, const std::string& sdp_answer) {
        std::scoped_lock lock(clients_mutex_);
        auto it = clients_.find(client_id);
        if (it == clients_.end()) {
            return false;
        }
        try {
            const bool has_h264 = sdp_answer.find("H264/90000") != std::string::npos;
            VA_LOG_INFO() << "[WebRTC] applying SDP answer for client " << client_id << ", size=" << sdp_answer.size() << " h264=" << has_h264;
            VA_LOG_DEBUG() << "[WebRTC] answer SDP (trunc):\n" << truncate_for_log(sdp_answer, 2048);
            rtc::Description answer(sdp_answer, rtc::Description::Type::Answer);
            it->second->peer_connection->setRemoteDescription(answer);
            return true;
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "Failed to apply answer for client " << client_id << ": " << ex.what();
            return false;
        }
    }

    bool AddIceCandidate(const std::string& client_id, const Json::Value& candidate) {
        std::scoped_lock lock(clients_mutex_);
        auto it = clients_.find(client_id);
        if (it == clients_.end()) {
            return false;
        }
        try {
            const std::string cand = candidate.get("candidate", "").asString();
            std::string typ = "?";
            auto pos = cand.find(" typ ");
            if (pos != std::string::npos && pos + 6 < cand.size()) {
                size_t end = cand.find(' ', pos + 5);
                if (end == std::string::npos) end = cand.size();
                typ = cand.substr(pos + 5, end - (pos + 5));
            }
            VA_LOG_DEBUG() << "[WebRTC] add ICE candidate for client " << client_id
                           << " mid=" << candidate.get("sdpMid", "").asString()
                           << " typ=" << typ
                           << " len=" << cand.size()
                           << " cand=" << truncate_for_log(cand, 512);
            {
                std::string mid = candidate.get("sdpMid", "").asString();
                if (mid.empty() || mid == "0") {
                    // 兼容浏览器发送的通道 mid 异常：我们的视频轨 mid 固定为 "video"
                    mid = "video";
                    VA_LOG_DEBUG() << "[WebRTC] normalize remote ICE sdpMid -> 'video'";
                }
                rtc::Candidate rtc_candidate(candidate["candidate"].asString(), mid);
                it->second->peer_connection->addRemoteCandidate(rtc_candidate);
            }
            return true;
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "Failed to add ICE candidate for client " << client_id << ": " << ex.what();
            return false;
        }
    }

    void PushEncodedFrame(const std::string& source_id, std::vector<uint8_t>&& data) {
        video_source_->PushEncodedFrame(source_id, std::move(data));
    }

    void SetClientSource(const std::string& client_id, const std::string& source_id) {
        std::scoped_lock lock(clients_mutex_);
        auto it = clients_.find(client_id);
        if (it != clients_.end()) {
            it->second->requested_source = source_id;
        }
    }

    void SetOnClientConnected(std::function<void(const std::string&)> callback) {
        on_client_connected_ = std::move(callback);
    }

    void SetOnClientDisconnected(std::function<void(const std::string&)> callback) {
        on_client_disconnected_ = std::move(callback);
    }

    void SetOnSignalingMessage(std::function<void(const std::string&, const Json::Value&)> callback) {
        on_signaling_message_ = std::move(callback);
    }

private:
    struct ClientConnection {
        std::string client_id;
        std::string requested_source;
        std::shared_ptr<rtc::PeerConnection> peer_connection;
        std::shared_ptr<rtc::DataChannel> data_channel;
        std::shared_ptr<rtc::Track> video_track;
        uint32_t ssrc{0};
        bool connected;
    };

    std::shared_ptr<rtc::PeerConnection> CreatePeerConnection(const std::string& client_id) {
        try {
            auto peer_connection = std::make_shared<rtc::PeerConnection>(rtc_config_);
            peer_connection->onStateChange([this, client_id](rtc::PeerConnection::State state) {
                const bool connected = (state == rtc::PeerConnection::State::Connected);
                {
                    std::scoped_lock lock(clients_mutex_);
                    auto it = clients_.find(client_id);
                    if (it != clients_.end()) {
                        it->second->connected = connected;
                    }
                }
                VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                    << "peer state client=" << client_id << " -> " << state;

                if (connected) {
                    // 已连接，向浏览器请求关键帧，确保拿到 SPS/PPS
                    {
                        std::scoped_lock lk(clients_mutex_);
                        auto it = clients_.find(client_id);
                        if (it != clients_.end() && it->second->video_track) {
                            it->second->video_track->requestKeyframe();
                        }
                    }
                    if (on_client_connected_) {
                        on_client_connected_(client_id);
                    }
                } else {
                    // 仅在 Closed/Failed 时清理，避免瞬时的 connecting/disconnected 被误清理
                    if (state == rtc::PeerConnection::State::Closed || state == rtc::PeerConnection::State::Failed) {
                        bool removed = false;
                        {
                            std::scoped_lock lk(clients_mutex_);
                            removed = clients_.erase(client_id) > 0;
                            client_state_.erase(client_id);
                        }
                        if (removed) {
                    VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                        << "removed client after state=" << state << " client=" << client_id;
                        }
                        if (on_client_disconnected_) {
                            on_client_disconnected_(client_id);
                        }
                    }
                }
            });

            peer_connection->onIceStateChange([this, client_id](rtc::PeerConnection::IceState ice) {
                VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                    << "ICE state client=" << client_id << " -> " << ice;
                bool mark_connected = (ice == rtc::PeerConnection::IceState::Connected || ice == rtc::PeerConnection::IceState::Completed);
                {
                    std::scoped_lock lock(clients_mutex_);
                    auto it = clients_.find(client_id);
                    if (it != clients_.end()) {
                        it->second->connected = mark_connected;
                        if (mark_connected && it->second->video_track) {
                            it->second->video_track->requestKeyframe();
                        }
                    }
                }
                if (ice == rtc::PeerConnection::IceState::Closed) {
                    bool removed = false;
                    {
                        std::scoped_lock lk(clients_mutex_);
                        removed = clients_.erase(client_id) > 0;
                        client_state_.erase(client_id);
                    }
                    if (removed) {
                        VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                            << "removed client after ICE closed client=" << client_id;
                    }
                }
            });

            peer_connection->onGatheringStateChange([client_id](rtc::PeerConnection::GatheringState g) {
                VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
                    << "Gathering state client=" << client_id << " -> " << g;
            });

            peer_connection->onSignalingStateChange([client_id](rtc::PeerConnection::SignalingState s) {
                VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
                    << "Signaling state client=" << client_id << " -> " << s;
            });

            peer_connection->onLocalDescription([this, client_id](rtc::Description desc) {
                VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
                    << "local description client=" << client_id << " type=" << desc.typeString();
                try {
                    // 在自动协商或重建轨道时，libdatachannel 会触发新的 offer，这里将其通过信令转发给前端
                    if (on_signaling_message_ && desc.type() == rtc::Description::Type::Offer) {
                        std::string sdp = std::string(desc);
                        Json::Value payload;
                        payload["type"] = "offer";
                        payload["client_id"] = client_id;
                        payload["data"]["type"] = "offer";
                        payload["data"]["sdp"] = sdp;
                        payload["timestamp"] = static_cast<Json::Int64>(std::chrono::duration_cast<std::chrono::milliseconds>(
                            std::chrono::system_clock::now().time_since_epoch()).count());
                        VA_LOG_INFO() << "[WebRTC] auto-negotiation offer generated, len=" << sdp.size();
                        on_signaling_message_(client_id, payload);
                    }
                } catch (...) {}
            });

            peer_connection->onLocalCandidate([this, client_id](rtc::Candidate candidate) {
                const std::string cand_str = std::string(candidate);
                // 粗略解析 typ，便于排查（host/srflx/tcp 等）
                std::string typ = "?";
                auto pos = cand_str.find(" typ ");
                if (pos != std::string::npos && pos + 6 < cand_str.size()) {
                    size_t end = cand_str.find(' ', pos + 5);
                    if (end == std::string::npos) end = cand_str.size();
                    typ = cand_str.substr(pos + 5, end - (pos + 5));
                }
                VA_LOG_DEBUG() << "[WebRTC] local ICE candidate for client " << client_id
                               << " typ=" << typ << " len=" << cand_str.size()
                               << " cand=" << truncate_for_log(cand_str, 512);
                if (on_signaling_message_) {
                    Json::Value payload;
                    payload["type"] = "ice_candidate";
                    payload["client_id"] = client_id;
                    payload["data"]["candidate"] = (cand_str.rfind("a=", 0) == 0 ? cand_str.substr(2) : cand_str);
                    {
                        std::string mid = candidate.mid();
                        if (mid.empty() || mid == "0") mid = "video";
                        payload["data"]["sdpMid"] = mid;
                    }
                    on_signaling_message_(client_id, payload);
                }
            });

            return peer_connection;
        } catch (const std::exception& ex) {
                VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc")
                    << "Failed to create peer connection for client " << client_id << ": " << ex.what();
                return nullptr;
            }
        }

    void SendVideoFrames() {
        int frames_sent_count = 0;
        const size_t MAX_CHUNK_SIZE = 16384;
        auto t0 = std::chrono::steady_clock::now();
        auto last_diag = std::chrono::steady_clock::now();

            while (!should_stop_sender_) {
            std::vector<std::pair<std::string, std::string>> clients;
            {
                std::scoped_lock lock(clients_mutex_);
                for (auto& [client_id, client] : clients_) {
                    // 收集所有“已连接”的客户端；即使轨道暂时关闭，也在单个循环中尝试重建
                    if (client->connected) {
                        clients.emplace_back(client_id, client->requested_source);
                    }
                }
            }

            for (const auto& [client_id, requested_source] : clients) {
                std::string used_source = requested_source;
                std::vector<uint8_t> encoded_frame;
                if (video_source_->HasEncodedFrame(requested_source)) {
                    encoded_frame = video_source_->GetEncodedFrame(requested_source);
                } else {
                    std::string any_src;
                    std::vector<uint8_t> any_frame;
                    if (video_source_->TryGetAnyEncodedFrame(any_src, any_frame)) {
                        used_source = any_src;
                        encoded_frame = std::move(any_frame);
                        VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
                            << "fallback send: client='" << client_id
                            << "' requested='" << requested_source
                            << "' use='" << used_source << "'";
                    } else {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 1000)
                            << "client='" << client_id << "' waiting frames for source='" << requested_source << "' (no frames)";
                        continue;
                    }
                }
                if (encoded_frame.empty()) {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000)
                        << "client='" << client_id << "' got empty frame for source='" << used_source << "'";
                    continue;
                }

                std::shared_ptr<ClientConnection> client;
                {
                    std::scoped_lock lock(clients_mutex_);
                    auto it = clients_.find(client_id);
                    if (it == clients_.end()) {
                        continue;
                    }
                    client = it->second;
                    bool track_closed = true;
                    if (client->video_track) {
                        try { track_closed = client->video_track->isClosed(); } catch (...) { track_closed = true; }
                    }
                    // 尝试自动重建关闭的轨道，触发一次重新协商
                    if (client->connected && track_closed) {
                        try {
                            rtc::Description::Video vdesc("video");
                            vdesc.setDirection(rtc::Description::Direction::SendOnly);
                            vdesc.addH264Codec(96, rtc::DEFAULT_H264_VIDEO_PROFILE);
                            vdesc.addSSRC(client->ssrc ? client->ssrc : std::random_device{}(), std::string("va"), std::string("stream1"), std::string("video1"));
                            client->video_track = client->peer_connection->addTrack(vdesc);
                            attachMediaHandlers(client->video_track, client->ssrc);
                            VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                                << "recreated video track for client=" << client_id << " ssrc=" << (client->ssrc);
                            // 请求关键帧，确保包含 SPS/PPS
                            try { client->video_track->requestKeyframe(); } catch (...) {}
                            // 触发一次显式协商：生成新的 offer 并 setLocalDescription
                            try {
                                auto off = client->peer_connection->createOffer();
                                std::string sdp_offer = std::string(off);
                                client->peer_connection->setLocalDescription(rtc::Description::Type::Offer);
                                VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                                    << "renegotiation: createOffer + setLocalDescription triggered for client=" << client_id;
                                // 直接通过信令发送新的 offer（不依赖回调），确保前端收到
                                if (on_signaling_message_ && !sdp_offer.empty()) {
                                    Json::Value payload;
                                    payload["type"] = "offer";
                                    payload["client_id"] = client_id;
                                    payload["data"]["type"] = "offer";
                                    payload["data"]["sdp"] = sdp_offer;
                                    payload["timestamp"] = static_cast<Json::Int64>(std::chrono::duration_cast<std::chrono::milliseconds>(
                                        std::chrono::system_clock::now().time_since_epoch()).count());
                                    on_signaling_message_(client_id, payload);
                                    VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                                        << "renegotiation offer sent, len=" << sdp_offer.size();
                                }
                            } catch (const std::exception& ex2) {
                                VA_LOG_C(::va::core::LogLevel::Warn, "transport.webrtc")
                                    << "renegotiation failed (createOffer/setLocal) for client " << client_id << ": " << ex2.what();
                            }
                            // 重新评估关闭状态
                            try { track_closed = client->video_track->isClosed(); } catch (...) { track_closed = true; }
                        } catch (const std::exception& ex) {
                            VA_LOG_C(::va::core::LogLevel::Warn, "transport.webrtc")
                                << "recreate video track failed for client " << client_id << ": " << ex.what();
                        }
                    }
                    if (!client->connected || track_closed) {
                        continue;
                    }
                }

                // 仅通过 WebRTC 视频轨发送 H.264（让浏览器直接解码显示）
                try {
                    if (client->video_track) {
                        ensure_annexb(encoded_frame);
                        maybe_inject_param_sets(encoded_frame);
                        rtc::binary h264;
                        h264.resize(encoded_frame.size());
                        std::memcpy(h264.data(), encoded_frame.data(), encoded_frame.size());
                        // per-client RTP ts 与调度
                        if (!client_state_.count(client_id)) {
                            ClientState st; st.ts90 = 0; st.next_tp = std::chrono::steady_clock::now(); client_state_.emplace(client_id, st);
                        }
                        auto& st = client_state_.at(client_id);
                        rtc::FrameInfo finfo(st.ts90);
                        finfo.payloadType = 96; // must match SDP payload type
                        client->video_track->sendFrame(std::move(h264), finfo);
                        frames_sent_count++;
                        st.ts90 += (90000u / (fps_ > 0 ? fps_ : 30));
                        st.next_tp += std::chrono::nanoseconds(static_cast<int64_t>(1'000'000'000.0 / (fps_ > 0 ? fps_ : 30)));
                        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 1000)
                            << "tx frame: n=" << frames_sent_count << ", last=" << encoded_frame.size()
                            << "B src='" << used_source << "' client='" << client_id << "'";
                    }
                } catch (const std::exception& ex) {
                    VA_LOG_C(::va::core::LogLevel::Warn, "transport.webrtc")
                        << "Failed to send H264 on video track for client " << client_id << ": " << ex.what();
                }
            }

            // 选择最近的下一发送时刻休眠，保证固定节奏（无忙等）
            auto sleep_until_tp = std::chrono::steady_clock::now() + std::chrono::milliseconds(33);
            if (!client_state_.empty()) {
                for (const auto& kv : client_state_) {
                    if (kv.second.next_tp < sleep_until_tp) sleep_until_tp = kv.second.next_tp;
                }
            }
            auto now_tp = std::chrono::steady_clock::now();
            if (sleep_until_tp > now_tp + std::chrono::milliseconds(1)) {
                std::this_thread::sleep_until(sleep_until_tp);
            }

            // 每秒打印一次诊断，观测客户端状态与队列尺寸
            auto now = std::chrono::steady_clock::now();
            if (std::chrono::duration_cast<std::chrono::milliseconds>(now - last_diag).count() >= 1000) {
                last_diag = now;
                std::ostringstream oss;
                oss << "[WebRTC][diag] clients=";
                {
                    std::scoped_lock lock(clients_mutex_);
                    bool first = true;
                    for (auto& [cid, cptr] : clients_) {
                        bool closed = true;
                        if (cptr && cptr->video_track) {
                            try { closed = cptr->video_track->isClosed(); } catch (...) { closed = true; }
                        }
                        // queue size inspection
                        size_t qsz = video_source_->HasEncodedFrame(cptr ? cptr->requested_source : std::string()) ? 1 : 0;
                        if (!first) oss << "; "; first = false;
                        oss << cid << "(conn=" << (cptr && cptr->connected ? 1 : 0)
                            << ",closed=" << (closed ? 1 : 0)
                            << ",src='" << (cptr ? cptr->requested_source : std::string("?")) << "'"
                            << ",has=" << qsz << ")";
                    }
                }
                VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << oss.str();
            }
        }
    }

    bool initialized_;
    int port_;
    std::atomic<bool> should_stop_sender_;
    rtc::Configuration rtc_config_;
    std::unique_ptr<WebRTCVideoSource> video_source_;
    // RTP/媒体发送可调参数（来自环境变量，不改变对外接口）
    size_t mtu_ {1200};
    unsigned pace_bps_ {0}; // 0=关闭，UINT_MAX=auto
    int fps_ {30};
    mutable std::mutex clients_mutex_;
    std::map<std::string, std::shared_ptr<ClientConnection>> clients_;
    std::function<void(const std::string&)> on_client_connected_;
    std::function<void(const std::string&)> on_client_disconnected_;
    std::function<void(const std::string&, const Json::Value&)> on_signaling_message_;
    std::thread video_sender_thread_;
    struct ClientState { uint32_t ts90{0}; std::chrono::steady_clock::time_point next_tp{}; };
    std::map<std::string, ClientState> client_state_;

    void attachMediaHandlers(const std::shared_ptr<rtc::Track>& track, uint32_t ssrc) {
        try {
            auto rtpCfg = std::make_shared<rtc::RtpPacketizationConfig>(ssrc, std::string("va"), static_cast<uint8_t>(96), rtc::H264RtpPacketizer::ClockRate);
            size_t maxFrag = (mtu_ > 200 ? (mtu_ - 200) : 1000);
            auto h264pack = std::make_shared<rtc::H264RtpPacketizer>(rtc::NalUnit::Separator::StartSequence, rtpCfg, maxFrag);
            track->setMediaHandler(h264pack);
            unsigned use_pace = pace_bps_;
            if (use_pace == UINT_MAX) {
                // auto: 默认 8Mbps 上限，主要用于平滑 I 帧突发
                use_pace = 8'000'000u;
            }
            if (use_pace > 0) {
                auto pacing = std::make_shared<rtc::PacingHandler>(static_cast<double>(use_pace), std::chrono::milliseconds(8));
                track->chainMediaHandler(pacing);
            }
            VA_LOG_INFO() << "[WebRTC] media handlers attached: mtu=" << mtu_ << ", pace_bps=" << use_pace;
        } catch (const std::exception& ex) {
            VA_LOG_WARN() << "[WebRTC] attach media handlers failed: " << ex.what();
        }
    }
};

// --- Minimal H.264 NAL helpers for SPS/PPS injection on IDR ---
static inline bool is_start_code3(const uint8_t* p) { return p[0]==0x00 && p[1]==0x00 && p[2]==0x01; }
static inline bool is_start_code4(const uint8_t* p) { return p[0]==0x00 && p[1]==0x00 && p[2]==0x00 && p[3]==0x01; }
static inline int nal_type_at(const std::vector<uint8_t>& b, size_t a) {
    size_t sc = (a+2<b.size() && b[a+2]==0x01) ? 3 : 4; if (a+sc>=b.size()) return -1; return b[a+sc] & 0x1F;
}

static inline void maybe_inject_param_sets(std::vector<uint8_t>& frame) {
    if (frame.size() < 6) return;
    // scan NAL start positions
    std::vector<size_t> pos; pos.reserve(16);
    for (size_t i=0; i+4<=frame.size(); ++i) {
        if (is_start_code3(&frame[i]) || is_start_code4(&frame[i])) pos.push_back(i);
    }
    if (pos.empty()) return;
    pos.push_back(frame.size());
    bool has_sps=false, has_pps=false, is_idr=false;
    for (size_t i=0; i+1<pos.size(); ++i) {
        int nt = nal_type_at(frame, pos[i]);
        if (nt==7) has_sps=true; else if (nt==8) has_pps=true; else if (nt==5) is_idr=true;
    }
    if (!is_idr || (has_sps && has_pps)) return;
    // cache last seen SPS/PPS across calls
    static std::vector<uint8_t> last_sps, last_pps;
    // update cache from current frame if possible
    for (size_t i=0; i+1<pos.size(); ++i) {
        int nt = nal_type_at(frame, pos[i]);
        if (nt==7) { last_sps.assign(frame.begin()+pos[i], frame.begin()+pos[i+1]); }
        else if (nt==8) { last_pps.assign(frame.begin()+pos[i], frame.begin()+pos[i+1]); }
    }
    if ((!has_sps || !has_pps) && (!last_sps.empty() || !last_pps.empty())) {
        // prepend cached SPS/PPS before first NAL
        std::vector<uint8_t> out; out.reserve(frame.size()+last_sps.size()+last_pps.size());
        if (!last_sps.empty()) out.insert(out.end(), last_sps.begin(), last_sps.end());
        if (!last_pps.empty()) out.insert(out.end(), last_pps.begin(), last_pps.end());
        out.insert(out.end(), frame.begin(), frame.end());
        frame.swap(out);
    }
}

} // namespace

struct WebRTCDataChannelTransport::Impl {
    static std::mutex& globalMutex() { static std::mutex m; return m; }
    static std::atomic<bool>& globalStarted() { static std::atomic<bool> s{false}; return s; }

    bool ensureStarted(const std::string& endpoint) {
        if (running_) {
            return true;
        }

        std::scoped_lock lg(globalMutex());
        endpoint_ = endpoint.empty() ? std::string(kDefaultEndpoint) : endpoint;
        const uint16_t port = parsePort(endpoint_);

        if (!globalStarted().load()) {
            streamer_.SetOnSignalingMessage([this](const std::string& client_id, const Json::Value& message) {
                signaling_.sendToClient(client_id, message);
            });

            streamer_.SetOnClientConnected([this](const std::string&) {
                std::scoped_lock lock(mutex_);
                aggregate_.connected = true;
            });

            streamer_.SetOnClientDisconnected([this](const std::string&) {
                std::scoped_lock lock(mutex_);
                aggregate_.connected = false;
            });

            signaling_.setMessageCallback([this](const std::string& client_id, const Json::Value& message) {
                handleSignalingMessage(client_id, message);
            });

            if (!streamer_.Initialize(kDefaultStreamerPort)) {
                return false;
            }
            if (!signaling_.start(port)) {
                streamer_.Shutdown();
                return false;
            }
            globalStarted().store(true);
        }

        running_ = true;
        return true;
    }

    void stop() {
        if (!running_) {
            return;
        }
        // Keep global streamer/signaling running to avoid short restarts
        std::scoped_lock lock(mutex_);
        track_stats_.clear();
        aggregate_ = {};
        running_ = false;
    }

    bool sendPacket(const std::string& track_id, const uint8_t* data, size_t size) {
        if (!running_ || !data || size == 0) {
            return false;
        }

        // Normalize key so that it matches requested_source (usually plain stream id without profile suffix)
        std::string key = track_id;
        auto pos = key.find(':');
        if (pos != std::string::npos) key = key.substr(0, pos);

        std::vector<uint8_t> buffer(data, data + size);
        streamer_.PushEncodedFrame(key, std::move(buffer));

        std::scoped_lock lock(mutex_);
        auto& stat = track_stats_[track_id];
        stat.connected = true;
        stat.packets += 1;
        stat.bytes += static_cast<uint64_t>(size);
        if (stat.packets == 1 || (stat.packets % 30 == 0)) {
            VA_LOG_INFO() << "[WebRTC] enqueue frame track='" << track_id << "' key='" << key
                          << "' bytes=" << size << " pkts=" << stat.packets << ", total_bytes=" << stat.bytes;
        }
        aggregate_.connected = true;
        aggregate_.packets += 1;
        aggregate_.bytes += static_cast<uint64_t>(size);
        return true;
    }

    ITransport::Stats aggregateStats() const {
        std::scoped_lock lock(mutex_);
        return aggregate_;
    }

    void handleSignalingMessage(const std::string& client_id, const Json::Value& message) {
        const std::string type = message.get("type", "").asString();
        VA_LOG_DEBUG() << "[Signaling] dispatch -> client=" << client_id
                       << " type='" << type << "' payload=" << json_to_string_trunc(message);
        if (type == "request_offer") {
            std::string source = "camera_01";
            if (message.isMember("data")) {
                source = sanitizeTrackId(message["data"].get("source_id", "").asString());
            }

            streamer_.SetClientSource(client_id, source);

            std::string offer;
            if (!streamer_.CreateOffer(client_id, offer)) {
                Json::Value err;
                err["type"] = "offer_error";
                err["message"] = "failed to create offer";
                signaling_.sendToClient(client_id, err);
                return;
            }

            Json::Value payload;
            payload["type"] = "offer";
            payload["client_id"] = client_id;
            payload["data"]["type"] = "offer";
            payload["data"]["sdp"] = offer;
            payload["timestamp"] = static_cast<Json::Int64>(std::chrono::duration_cast<std::chrono::milliseconds>(
                std::chrono::system_clock::now().time_since_epoch()).count());
            VA_LOG_DEBUG() << "[Signaling] send offer -> sdpLen=" << offer.size()
                           << " sdp(trunc)=\n" << truncate_for_log(offer, 2048);
            signaling_.sendToClient(client_id, payload);
        } else if (type == "answer") {
            std::string sdp;
            if (message.isMember("data")) {
                sdp = message["data"].get("sdp", "").asString();
            }
            if (!sdp.empty()) {
                VA_LOG_DEBUG() << "[Signaling] recv answer <- sdpLen=" << sdp.size()
                               << " sdp(trunc)=\n" << truncate_for_log(sdp, 2048);
                streamer_.HandleAnswer(client_id, sdp);
            }
        } else if (type == "ice_candidate") {
            if (message.isMember("data")) {
                const std::string cand = message["data"].get("candidate", "").asString();
                VA_LOG_DEBUG() << "[Signaling] recv remote ICE <- len=" << cand.size()
                               << " cand=" << truncate_for_log(cand, 512);
                streamer_.AddIceCandidate(client_id, message["data"]);
            }
        } else if (type == "switch_source") {
            if (message.isMember("data")) {
                std::string source = sanitizeTrackId(message["data"].get("source_id", "").asString());
                VA_LOG_INFO() << "[Signaling] switch_source -> client=" << client_id << " source_id='" << source << "'";
                streamer_.SetClientSource(client_id, source);
            }
        }
    }

    SignalingServer signaling_;
    WebRTCStreamer streamer_;
    bool running_{false};
    std::string endpoint_;
    mutable std::mutex mutex_;
    std::unordered_map<std::string, ITransport::Stats> track_stats_;
    ITransport::Stats aggregate_;
};

WebRTCDataChannelTransport::WebRTCDataChannelTransport()
    : impl_(std::make_shared<Impl>()) {}

WebRTCDataChannelTransport::~WebRTCDataChannelTransport() {
    disconnect();
}

bool WebRTCDataChannelTransport::connect(const std::string& endpoint) {
    return impl_ && impl_->ensureStarted(endpoint);
}

bool WebRTCDataChannelTransport::send(const std::string& track_id, const uint8_t* data, size_t size) {
    if (!impl_) {
        return false;
    }
    return impl_->sendPacket(track_id, data, size);
}

void WebRTCDataChannelTransport::disconnect() {
    if (impl_) {
        impl_->stop();
    }
}

ITransport::Stats WebRTCDataChannelTransport::stats() const {
    if (!impl_) {
        return {};
    }
    return impl_->aggregateStats();
}

} // namespace va::media

// Ensure H.264 bitstream is Annex B (0x00000001 start codes). If input appears to be AVCC (length-prefixed),
// convert to Annex B by rewriting each NAL with a 4-byte start code.
static inline void ensure_annexb(std::vector<uint8_t>& buf) {
    if (buf.size() < 4) return;
    if (buf[0] == 0x00 && buf[1] == 0x00 && buf[2] == 0x00 && buf[3] == 0x01) return; // already Annex B
    // Try AVCC conversion
    std::vector<uint8_t> out;
    size_t pos = 0;
    auto push_sc = [&out]() { const uint8_t sc[4] = {0,0,0,1}; out.insert(out.end(), sc, sc+4); };
    while (pos + 4 <= buf.size()) {
        uint32_t len = (static_cast<uint32_t>(buf[pos]) << 24) | (static_cast<uint32_t>(buf[pos+1]) << 16)
                     | (static_cast<uint32_t>(buf[pos+2]) << 8)  | (static_cast<uint32_t>(buf[pos+3]));
        pos += 4;
        if (len == 0 || pos + len > buf.size()) { // invalid, abort conversion
            return;
        }
        push_sc();
        out.insert(out.end(), buf.begin()+pos, buf.begin()+pos+len);
        pos += len;
    }
    if (!out.empty()) buf.swap(out);
}
