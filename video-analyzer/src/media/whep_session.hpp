#pragma once

#if defined(__has_include)
#  if __has_include(<rtc/rtc.hpp>)
#    define VA_HAVE_RTC 1
#    include <rtc/rtc.hpp>
#    include <rtc/h264rtppacketizer.hpp>
#    include <rtc/pacinghandler.hpp>
#  else
#    define VA_HAVE_RTC 0
#  endif
#else
#  define VA_HAVE_RTC 0
#endif

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

struct H264SpsInfo {
    uint32_t id{0};
    uint32_t log2_max_frame_num{8};
    uint32_t pic_order_cnt_type{0};
    uint32_t log2_max_pic_order_cnt_lsb{8};
    bool separate_colour_plane_flag{false};
    bool frame_mbs_only_flag{true};
    bool delta_pic_order_always_zero_flag{false};
    bool valid{false};
};

struct H264PpsInfo {
    uint32_t id{0};
    uint32_t sps_id{0};
    bool pic_order_present_flag{false};
    bool valid{false};
};

struct H264FrameState {
    bool have_prev{false};
    uint32_t frame_num{0};
    uint32_t pic_order_cnt_lsb{0};
    bool has_poc_lsb{false};
    bool is_idr{false};
    bool field_pic{false};
};

// Minimal WHEP session管理：基于 libdatachannel，按 streamKey 发送 H264 RTP 视频轨
class WhepSessionManager {
public:
    static WhepSessionManager& instance();
    struct Config {
      std::string bind_address;  // e.g., "0.0.0.0"
      std::string public_ip;     // e.g., "192.168.50.78" (for SDP rewrite)
      uint16_t port_begin {10000};
      uint16_t port_end   {10100};
      bool disable_mdns { true };
    };
    void setConfig(const Config& c) { std::lock_guard<std::mutex> g(mu_); cfg_ = c; }

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

  // Query whether there is at least one active WHEP session subscribed to streamKey
  bool hasActiveForKey(const std::string& streamKey);

  private:
    Config cfg_{};
    WhepSessionManager() = default;

    #if VA_HAVE_RTC
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
        std::unordered_map<uint32_t, H264SpsInfo> sps_map;
        std::unordered_map<uint32_t, H264PpsInfo> pps_map;
        H264FrameState frame_state;
        std::vector<uint8_t> pending_prefix; // NAL units collected before the next access unit
        bool prefix_has_sps{false};
        bool prefix_has_pps{false};
        std::vector<uint8_t> pending_au; // assembling access unit (AnnexB with start codes)
        bool pending_has_vcl{false};
        bool pending_is_idr{false};
        bool pending_has_sps{false};
        bool pending_has_pps{false};
        std::chrono::steady_clock::time_point pending_started_at{};
        // debug counters
        uint64_t dbg_frames{0};
        uint64_t dbg_bytes{0};
    };
    #else
    struct Session { };
    #endif

    void attachMediaHandlers(Session& s);
    static std::string genSid();

    std::mutex mu_;
    std::unordered_map<std::string, std::shared_ptr<Session>> bySid_;
    // 允许同一流多会话：streamKey -> [sid]
    std::unordered_multimap<std::string, std::string> indexByStream_;
};

} // namespace va::media

#if !VA_HAVE_RTC
// Provide inline stub implementations when libdatachannel headers are unavailable
namespace va::media {
inline WhepSessionManager& WhepSessionManager::instance() {
    static WhepSessionManager inst; return inst;
}
inline int WhepSessionManager::createSession(const std::string&, const std::string&, std::string& outAns, std::string& outSid) {
    outAns.clear(); outSid.clear(); return 501; /* Not Implemented */
}
inline int WhepSessionManager::patchSession(const std::string&, const std::string&) { return 501; }
inline int WhepSessionManager::deleteSession(const std::string&) { return 404; }
inline void WhepSessionManager::feedFrame(const std::string&, const std::vector<uint8_t>&) {}
inline bool WhepSessionManager::hasActiveForKey(const std::string&) { return false; }
}
#endif
