#include "media/transport_webrtc_datachannel.hpp"

#include "core/logger.hpp"

#include <ixwebsocket/IXWebSocketServer.h>
#include <json/json.h>
#include <rtc/rtc.hpp>

#include <algorithm>
#include <atomic>
#include <chrono>
#include <cctype>
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
                if (msg_type == "auth") {
                    auto clients = server_->getClients();
                    for (auto client : clients) {
                        if (client.get() == &webSocket) {
                            handleClientAuthentication(std::weak_ptr<ix::WebSocket>(client), json_msg);
                            break;
                        }
                    }
                } else {
                    std::scoped_lock lock(clients_mutex_);
                    for (auto& [weak_ws, client_id] : connection_to_client_) {
                        if (auto shared_ws = weak_ws.lock()) {
                            if (shared_ws.get() == &webSocket) {
                                if (message_callback_) {
                                    message_callback_(client_id, json_msg);
                                }
                                break;
                            }
                        }
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
            rtc_config_.enableIceTcp = false;
            rtc_config_.disableAutoNegotiation = false;
            rtc_config_.portRangeBegin = 10000;
            rtc_config_.portRangeEnd = 10100;
            rtc_config_.bindAddress = "127.0.0.1";

            should_stop_sender_ = false;
            video_sender_thread_ = std::thread(&WebRTCStreamer::SendVideoFrames, this);

            initialized_ = true;
            VA_LOG_INFO() << "WebRTC streamer initialized on port " << port;
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
            client->data_channel = peer_connection->createDataChannel("video");

            client->data_channel->onOpen([client_id]() {
                VA_LOG_INFO() << "Data channel opened for client " << client_id;
            });

            client->data_channel->onClosed([client_id]() {
                VA_LOG_INFO() << "Data channel closed for client " << client_id;
            });

            {
                std::scoped_lock lock(clients_mutex_);
                clients_[client_id] = std::move(client);
            }

            auto offer_desc = peer_connection->createOffer();
            peer_connection->setLocalDescription(rtc::Description::Type::Offer);
            sdp_offer = std::string(offer_desc);
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
            rtc::Candidate rtc_candidate(candidate["candidate"].asString(), candidate["sdpMid"].asString());
            it->second->peer_connection->addRemoteCandidate(rtc_candidate);
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

                if (connected) {
                    if (on_client_connected_) {
                        on_client_connected_(client_id);
                    }
                } else {
                    if (on_client_disconnected_) {
                        on_client_disconnected_(client_id);
                    }
                }
            });

            peer_connection->onLocalCandidate([this, client_id](rtc::Candidate candidate) {
                if (on_signaling_message_) {
                    Json::Value payload;
                    payload["type"] = "ice_candidate";
                    payload["client_id"] = client_id;
                    payload["data"]["candidate"] = std::string(candidate);
                    payload["data"]["sdpMid"] = candidate.mid();
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

        while (!should_stop_sender_) {
            std::vector<std::pair<std::string, std::string>> clients;
            {
                std::scoped_lock lock(clients_mutex_);
                for (auto& [client_id, client] : clients_) {
                    if (client->connected && client->data_channel && client->data_channel->isOpen()) {
                        clients.emplace_back(client_id, client->requested_source);
                    }
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
                    if (!client->connected || !client->data_channel || !client->data_channel->isOpen()) {
                        continue;
                    }
                }

                try {
                    uint32_t total_size = static_cast<uint32_t>(encoded_frame.size());
                    if (total_size <= MAX_CHUNK_SIZE - 4) {
                        std::string packet(4 + encoded_frame.size(), '\0');
                        packet[0] = static_cast<char>((total_size >> 24) & 0xFF);
                        packet[1] = static_cast<char>((total_size >> 16) & 0xFF);
                        packet[2] = static_cast<char>((total_size >> 8) & 0xFF);
                        packet[3] = static_cast<char>(total_size & 0xFF);
                        std::memcpy(packet.data() + 4, encoded_frame.data(), encoded_frame.size());
                        client->data_channel->send(packet);
                    } else {
                        std::string header(4, '\0');
                        header[0] = static_cast<char>((total_size >> 24) & 0xFF);
                        header[1] = static_cast<char>((total_size >> 16) & 0xFF);
                        header[2] = static_cast<char>((total_size >> 8) & 0xFF);
                        header[3] = static_cast<char>(total_size & 0xFF);
                        client->data_channel->send(header);

                        size_t offset = 0;
                        while (offset < encoded_frame.size()) {
                            size_t chunk_size = encoded_frame.size() - offset;
                            if (chunk_size > MAX_CHUNK_SIZE) {
                                chunk_size = MAX_CHUNK_SIZE;
                            }
                            std::string chunk_buffer(chunk_size, '\0');
                            std::memcpy(chunk_buffer.data(), encoded_frame.data() + offset, chunk_size);
                            client->data_channel->send(chunk_buffer);
                            offset += chunk_size;
                            std::this_thread::sleep_for(std::chrono::milliseconds(1));
                        }
                    }

                    frames_sent_count++;
                } catch (const std::exception& ex) {
                    VA_LOG_WARN() << "Failed to send frame to client " << client_id << ": " << ex.what();
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

        std::vector<uint8_t> buffer(data, data + size);
        streamer_.PushEncodedFrame(track_id, std::move(buffer));

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
            signaling_.sendToClient(client_id, payload);
        } else if (type == "answer") {
            std::string sdp;
            if (message.isMember("data")) {
                sdp = message["data"].get("sdp", "").asString();
            }
            if (!sdp.empty()) {
                streamer_.HandleAnswer(client_id, sdp);
            }
        } else if (type == "ice_candidate") {
            if (message.isMember("data")) {
                streamer_.AddIceCandidate(client_id, message["data"]);
            }
        } else if (type == "switch_source") {
            if (message.isMember("data")) {
                std::string source = sanitizeTrackId(message["data"].get("source_id", "").asString());
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
