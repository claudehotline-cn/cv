#pragma once

#include <rtc/rtc.hpp>
#include <rtc/h264rtppacketizer.hpp>
#include <rtc/pacinghandler.hpp>

#include <atomic>
#include <chrono>
#include <cstdint>
#include <map>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <utility>
#include <vector>

namespace va::media {

// Minimal WHEP session管理：基于 libdatachannel，按 streamKey 发送 H264 RTP 视频轨
class WhepSessionManager {
public:
    static WhepSessionManager& instance();

    // 创建会话：输入 streamKey（如 "cam01:det_720p" 或 "cam01"），与浏览器 Offer SDP。
    // 输出 Answer SDP 与 session id（用于 Location: /whep/sessions/{sid}）。
    // 返回 HTTP 状态码（201 成功，4xx/5xx 失败）。
    int createSession(const std::string& streamKey,
                      const std::string& offerSdp,
                      std::string& outAnswerSdp,
                      std::string& outSid);

    // 处理客户端 Trickle ICE 片段（可选）。返回 204 或 4xx。
    int patchSession(const std::string& sid, const std::string& sdpFrag);

    // 删除会话（显式关闭）。返回 204 或 404。
    int deleteSession(const std::string& sid);

    // 向匹配 streamKey 的会话喂入一帧 H264（AnnexB/AVCC 自动兼容）。
    void feedFrame(const std::string& streamKey, const std::vector<uint8_t>& h264);

private:
    WhepSessionManager() = default;

    struct Session {
        std::string sid;
        std::string streamKey;
        std::string mid; // negotiated mid for video m-line
        uint32_t ssrc{0};
        std::shared_ptr<rtc::PeerConnection> pc;
        std::shared_ptr<rtc::Track> videoTrack;
        std::shared_ptr<rtc::RtpPacketizationConfig> rtpCfg;
        std::shared_ptr<rtc::H264RtpPacketizer> h264pack;
        std::shared_ptr<rtc::PacingHandler> pacing;
        uint32_t ts90{0};
        std::chrono::steady_clock::time_point lastActive{};
        std::chrono::steady_clock::time_point createdAt{};
        std::chrono::steady_clock::time_point lastSentAt{};
        double avgMs{33.33};
        std::atomic<bool> closed{false};
        std::atomic<bool> started{false}; // set true after first IDR is observed to ensure decoders have a clean starting point
        std::atomic<bool> pcConnected{false}; // set true on PeerConnection::State::Connected
        uint8_t payloadType{96}; // negotiated H264 PT (default 96)
        std::atomic<bool> trackOpen{false}; // Track open callback observed
        std::vector<uint8_t> last_sps; // cached SPS (AnnexB unit with start code)
        std::vector<uint8_t> last_pps; // cached PPS (AnnexB unit with start code)
        // debug counters
        uint64_t dbg_frames{0};
        uint64_t dbg_bytes{0};
    };

    void attachMediaHandlers(Session& s);
    static std::string genSid();

    std::mutex mu_;
    std::unordered_map<std::string, std::shared_ptr<Session>> bySid_;
    // 允许同一流多会话：streamKey -> [sid]
    std::unordered_multimap<std::string, std::string> indexByStream_;
};

} // namespace va::media
