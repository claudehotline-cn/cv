#include "media/transport_webrtc_datachannel.hpp"

#include "core/logger.hpp"

#include <ixwebsocket/IXWebSocketServer.h>
#include <json/json.h>
#include <rtc/rtc.hpp>
#include <rtc/h264rtppacketizer.hpp>

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
#include <random>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>

namespace va::media {

namespace {

constexpr uint16_t kDefaultSignalingPort = 8083;
constexpr uint16_t kDefaultStreamerPort = 8080;
constexpr char kDefaultEndpoint[] = "ws://127.0.0.1:8083";

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
                } else {
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
        while (queue.size() > 10) {
            queue.pop();
        }
    }

    bool HasEncodedFrame(const std::string& source_id) const {
        std::scoped_lock lock(mutex_);
        auto it = frames_.find(source_id);
        return it != frames_.end() && !it->second.empty();
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

            // 仅添加视频轨（H264），暂不创建 DataChannel，避免 m=video 被禁用导致的 BUNDLE 异常
            try {
                rtc::Description::Video vdesc("video");
                vdesc.addH264Codec(96, rtc::DEFAULT_H264_VIDEO_PROFILE);
                VA_LOG_INFO() << "[WebRTC] adding video track mid='video' codec=H264 pt=96 for client " << client_id;
                client->video_track = peer_connection->addTrack(vdesc);
                // Explicitly set H264 RTP packetizer to be safe
                try {
                    auto h = std::make_shared<rtc::H264RtpPacketizer>();
                    h->setPayloadType(96);
                    client->video_track->setMediaHandler(h);
                } catch (...) {}
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
                VA_LOG_INFO() << "[WebRTC] peer state client=" << client_id << " -> " << state;

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
                    if (on_client_disconnected_) {
                        on_client_disconnected_(client_id);
                    }
                }
            });

            peer_connection->onIceStateChange([this, client_id](rtc::PeerConnection::IceState ice) {
                VA_LOG_INFO() << "[WebRTC] ICE state client=" << client_id << " -> " << ice;
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
            });

            peer_connection->onGatheringStateChange([client_id](rtc::PeerConnection::GatheringState g) {
                VA_LOG_DEBUG() << "[WebRTC] Gathering state client=" << client_id << " -> " << g;
            });

            peer_connection->onSignalingStateChange([client_id](rtc::PeerConnection::SignalingState s) {
                VA_LOG_DEBUG() << "[WebRTC] Signaling state client=" << client_id << " -> " << s;
            });

            peer_connection->onLocalDescription([client_id](rtc::Description desc) {
                VA_LOG_DEBUG() << "[WebRTC] local description client=" << client_id << " type=" << desc.typeString();
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
            VA_LOG_ERROR() << "Failed to create peer connection for client " << client_id << ": " << ex.what();
            return nullptr;
        }
    }

    void SendVideoFrames() {
        int frames_sent_count = 0;
        const size_t MAX_CHUNK_SIZE = 16384;
        auto t0 = std::chrono::steady_clock::now();

        while (!should_stop_sender_) {
            std::vector<std::pair<std::string, std::string>> clients;
            {
                std::scoped_lock lock(clients_mutex_);
                for (auto& [client_id, client] : clients_) {
                    // Send frames when peer is connected or track is open
                    bool ready = client->connected;
                    if (!ready && client->video_track) {
                        try { ready = client->video_track->isOpen(); } catch (...) {}
                    }
                    if (ready) clients.emplace_back(client_id, client->requested_source);
                }
            }

            for (const auto& [client_id, requested_source] : clients) {
                if (!video_source_->HasEncodedFrame(requested_source)) {
                    continue;
                }
                auto encoded_frame = video_source_->GetEncodedFrame(requested_source);
                if (encoded_frame.empty()) {
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
                    if (!client->connected) {
                        continue;
                    }
                }

                // 仅通过 WebRTC 视频轨发送 H.264（让浏览器直接解码显示）
                try {
                    if (client->video_track) {
                        ensure_annexb(encoded_frame);
                        rtc::binary h264;
                        h264.resize(encoded_frame.size());
                        std::memcpy(h264.data(), encoded_frame.data(), encoded_frame.size());
                        auto now = std::chrono::steady_clock::now();
                        auto elapsed = std::chrono::duration<double>(now - t0);
                        rtc::FrameInfo finfo(elapsed);
                        finfo.payloadType = 96; // must match SDP payload type
                        client->video_track->sendFrame(std::move(h264), finfo);
                        frames_sent_count++;
                        if (frames_sent_count % 30 == 0) {
                            VA_LOG_INFO() << "[WebRTC] tx video frame: +30 (last=" << encoded_frame.size() << " bytes)";
                        }
                    }
                } catch (const std::exception& ex) {
                    VA_LOG_WARN() << "Failed to send H264 on video track for client " << client_id << ": " << ex.what();
                }
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(33));
        }
    }

    bool initialized_;
    int port_;
    std::atomic<bool> should_stop_sender_;
    rtc::Configuration rtc_config_;
    std::unique_ptr<WebRTCVideoSource> video_source_;
    mutable std::mutex clients_mutex_;
    std::map<std::string, std::shared_ptr<ClientConnection>> clients_;
    std::function<void(const std::string&)> on_client_connected_;
    std::function<void(const std::string&)> on_client_disconnected_;
    std::function<void(const std::string&, const Json::Value&)> on_signaling_message_;
    std::thread video_sender_thread_;
};

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
