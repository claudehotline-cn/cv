#include "media/whep_session.hpp"

#include "core/logger.hpp"

#include <algorithm>
#include <random>
#include <sstream>

namespace va::media {

// Helper:确保 AnnexB 起始码
static inline void ensure_annexb(std::vector<uint8_t>& buf) {
    if (buf.size() < 4) return;
    if (buf[0] == 0x00 && buf[1] == 0x00 && buf[2] == 0x00 && buf[3] == 0x01) return;
    std::vector<uint8_t> out; out.reserve(buf.size()+16);
    size_t pos = 0; auto push_sc=[&](){ const uint8_t sc[4]={0,0,0,1}; out.insert(out.end(), sc, sc+4); };
    while (pos + 4 <= buf.size()) {
        uint32_t len = (uint32_t(buf[pos])<<24) | (uint32_t(buf[pos+1])<<16) | (uint32_t(buf[pos+2])<<8) | (uint32_t(buf[pos+3]));
        pos += 4; if (len == 0 || pos + len > buf.size()) return; push_sc();
        out.insert(out.end(), buf.begin()+pos, buf.begin()+pos+len); pos += len;
    }
    if (!out.empty()) buf.swap(out);
}

WhepSessionManager& WhepSessionManager::instance() {
    static WhepSessionManager g;
    return g;
}

std::string WhepSessionManager::genSid() {
    static std::atomic<uint64_t> ctr{1};
    std::ostringstream oss; oss << std::hex << std::random_device{}() << ctr.fetch_add(1);
    return oss.str();
}

void WhepSessionManager::attachMediaHandlers(Session& s) {
    const size_t maxFrag = 1200;
    s.rtpCfg = std::make_shared<rtc::RtpPacketizationConfig>(s.ssrc, std::string("va"), uint8_t(96), rtc::H264RtpPacketizer::ClockRate);
    s.h264pack = std::make_shared<rtc::H264RtpPacketizer>(rtc::NalUnit::Separator::StartSequence, s.rtpCfg, maxFrag);
    const double pace_bps = 1.0; // 默认启用节流，8ms tick
    s.pacing = std::make_shared<rtc::PacingHandler>(pace_bps, std::chrono::milliseconds(8));
    if (s.videoTrack) {
        // Attach H264 packetizer first, then pacing handler in chain
        s.videoTrack->setMediaHandler(s.h264pack);
        s.videoTrack->chainMediaHandler(s.pacing);
    }
}

int WhepSessionManager::createSession(const std::string& streamKey,
                                      const std::string& offerSdp,
                                      std::string& outAnswerSdp,
                                      std::string& outSid) {
    try {
        rtc::Configuration cfg; // host candidates 默认足够内网
        auto pc = std::make_shared<rtc::PeerConnection>(cfg);
        auto sid = genSid();

        auto sess = std::make_shared<Session>();
        sess->sid = sid;
        sess->streamKey = streamKey;
        sess->ssrc = std::random_device{}();
        sess->pc = pc;
        sess->lastActive = std::chrono::steady_clock::now();

        // 建立发送视频轨（H264/PT=96）
        rtc::Description::Video vdesc("video");
        vdesc.setDirection(rtc::Description::Direction::SendOnly);
        vdesc.addH264Codec(96, rtc::DEFAULT_H264_VIDEO_PROFILE);
        vdesc.addSSRC(sess->ssrc, std::string("va"), std::string("stream1"), std::string("video1"));
        sess->videoTrack = pc->addTrack(vdesc);
        attachMediaHandlers(*sess);

        std::mutex lmu; std::condition_variable lcv; bool haveLocal=false; std::string localSdp;
        pc->onLocalDescription([&](rtc::Description desc){
            if (desc.type() == rtc::Description::Type::Answer) {
                std::unique_lock<std::mutex> lk(lmu); localSdp = std::string(desc);
                haveLocal = true; lcv.notify_all();
            }
        });
        pc->onGatheringStateChange([&](rtc::PeerConnection::GatheringState g){ if (g == rtc::PeerConnection::GatheringState::Complete) { std::unique_lock<std::mutex> lk(lmu); lcv.notify_all(); } });
        pc->onStateChange([sess](rtc::PeerConnection::State st){ if (st==rtc::PeerConnection::State::Connected) sess->lastActive = std::chrono::steady_clock::now(); });

        // 设置远端与生成本地 Answer
        rtc::Description remote(offerSdp, rtc::Description::Type::Offer);
        pc->setRemoteDescription(remote);
        pc->setLocalDescription(rtc::Description::Type::Answer);

        // 等待 ICE 完成或超时，尽量返回完整 Answer（非 trickle）
        {
            std::unique_lock<std::mutex> lk(lmu);
            lcv.wait_for(lk, std::chrono::milliseconds(1500));
        }
        {
            std::unique_lock<std::mutex> lk(lmu);
            if (!haveLocal && localSdp.empty()) {
                // 兜底：直接抓取当前 local 描述
                try { auto loc = pc->localDescription(); if (loc) localSdp = std::string(*loc); } catch (...) {}
            }
        }
        if (localSdp.empty()) {
            return 500;
        }

        // 注册会话
        {
            std::lock_guard<std::mutex> g(mu_);
            bySid_[sid] = sess;
            indexByStream_.emplace(streamKey, sid);
        }

        outSid = sid;
        outAnswerSdp = localSdp;
        return 201;
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "[WHEP] createSession exception: " << ex.what();
        return 500;
    } catch (...) {
        return 500;
    }
}

int WhepSessionManager::patchSession(const std::string& sid, const std::string& sdpFrag) {
    std::shared_ptr<Session> sess;
    {
        std::lock_guard<std::mutex> g(mu_);
        auto it = bySid_.find(sid); if (it == bySid_.end()) return 404; sess = it->second;
    }
    if (!sess || !sess->pc) return 404;
    try {
        // 简易解析：查找 a=candidate 与 a=mid
        std::string cand; std::string mid("video");
        {
            std::istringstream iss(sdpFrag); std::string line;
            while (std::getline(iss, line)) {
                if (line.rfind("a=candidate:", 0) == 0) cand = line.substr(2); // drop "a="
                if (line.rfind("a=mid:", 0) == 0) mid = line.substr(6);
            }
        }
        if (!cand.empty()) {
            rtc::Candidate cnd(cand, mid);
            sess->pc->addRemoteCandidate(cnd);
        }
        return 204;
    } catch (...) {
        return 400;
    }
}

int WhepSessionManager::deleteSession(const std::string& sid) {
    std::shared_ptr<Session> sess;
    {
        std::lock_guard<std::mutex> g(mu_);
        auto it = bySid_.find(sid); if (it == bySid_.end()) return 404; sess = it->second;
        bySid_.erase(it);
        // 清理 stream 索引（可能有多个，逐个删除匹配项）
        for (auto i = indexByStream_.begin(); i != indexByStream_.end();) {
            if (i->second == sid) i = indexByStream_.erase(i); else ++i;
        }
    }
    try {
        if (sess->videoTrack) { try { sess->videoTrack->close(); } catch (...) {} }
        if (sess->pc) { try { sess->pc->close(); } catch (...) {} }
    } catch (...) {}
    return 204;
}

void WhepSessionManager::feedFrame(const std::string& streamKey, const std::vector<uint8_t>& data) {
    std::vector<std::pair<std::string, std::shared_ptr<Session>>> targets;
    {
        std::lock_guard<std::mutex> g(mu_);
        auto range = indexByStream_.equal_range(streamKey);
        for (auto it = range.first; it != range.second; ++it) {
            const auto& sid = it->second;
            auto sit = bySid_.find(sid);
            if (sit != bySid_.end() && sit->second && !sit->second->closed) {
                targets.emplace_back(sid, sit->second);
            }
        }
    }
    if (targets.empty()) return;

    for (auto& kv : targets) {
        auto sess = kv.second;
        if (!sess || !sess->videoTrack) continue;
        bool closed = false; try { closed = sess->videoTrack->isClosed(); } catch (...) { closed = true; }
        if (closed) { sess->closed = true; continue; }

        // Copy + normalize
        std::vector<uint8_t> h264 = data;
        ensure_annexb(h264);
        rtc::binary frame;
        frame.resize(h264.size());
        std::memcpy(frame.data(), h264.data(), h264.size());
        rtc::FrameInfo finfo(sess->ts90);
        try { sess->videoTrack->sendFrame(std::move(frame), finfo); } catch (...) { sess->closed = true; }
        sess->ts90 += (90000u / 30u);
        sess->lastActive = std::chrono::steady_clock::now();
    }
}

} // namespace va::media
