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
    // Use negotiated payload type if available (default 96)
    uint8_t pt = s.payloadType ? s.payloadType : uint8_t(96);
    s.rtpCfg = std::make_shared<rtc::RtpPacketizationConfig>(s.ssrc, std::string("va"), pt, rtc::H264RtpPacketizer::ClockRate);
    s.h264pack = std::make_shared<rtc::H264RtpPacketizer>(rtc::NalUnit::Separator::StartSequence, s.rtpCfg, maxFrag);
    // Optional pacing via env: VA_WHEP_PACE_BPS (bps). <=0 disables pacing.\n    double pace_bps = 0.0;\n    if (const char* pv = std::getenv("VA_WHEP_PACE_BPS"); pv && *pv) {\n        try { pace_bps = std::stod(pv); } catch (...) { pace_bps = 0.0; }\n    }\n    if (s.videoTrack) {\n        // Attach H264 packetizer first. Only chain pacing if explicitly enabled.\n        s.videoTrack->setMediaHandler(s.h264pack);\n        if (pace_bps > 0.0) {\n            s.pacing = std::make_shared<rtc::PacingHandler>(pace_bps, std::chrono::milliseconds(8));\n            s.videoTrack->chainMediaHandler(s.pacing);\n            VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pacing enabled bps=" << pace_bps;\n        }\n    }
}

int WhepSessionManager::createSession(const std::string& streamKey,
                                      const std::string& offerSdp,
                                      std::string& outAnswerSdp,
                                      std::string& outSid) {
    try {
        rtc::Configuration cfg; // host candidates 默认足够内网
        auto pc = std::make_shared<rtc::PeerConnection>(cfg);
        auto sid = genSid();
        VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
            << "[WHEP] createSession sid=" << sid << " stream='" << streamKey << "' offer_len=" << offerSdp.size();
        {
            std::string snip = offerSdp.substr(0, 200);
            for (auto& ch : snip) { if (ch=='\r' || ch=='\n') ch=' '; }
            VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc") << "[WHEP] offer_head=" << snip;
        }

        auto sess = std::make_shared<Session>();
        sess->sid = sid;
        sess->streamKey = streamKey;
        sess->ssrc = std::random_device{}();
        sess->pc = pc;
        sess->lastActive = std::chrono::steady_clock::now();

        // Parse Offer H264 PT and fix payloadType to Offer's mapping
        {
            auto parse_offer_h264_pt = [&](const std::string& sdp) -> uint8_t {
                std::istringstream iss(sdp);
                std::string line; std::string pt;
                while (std::getline(iss, line)) {
                    if (!line.empty() && line.back()=='\r') line.pop_back();
                    if (line.rfind("a=rtpmap:", 0)==0 && line.find("H264/90000")!=std::string::npos) {
                        size_t c = line.find(':'); size_t sp = line.find(' ', (c==std::string::npos?0:c+1));
                        if (c!=std::string::npos && sp!=std::string::npos && sp>c+1) { pt = line.substr(c+1, sp-(c+1)); break; }
                    }
                }
                if (pt.empty()) return uint8_t(96);
                try { int v = std::stoi(pt); if (v>=0 && v<=127) return uint8_t(v); } catch(...) {}
                return uint8_t(96);
            };
            sess->payloadType = parse_offer_h264_pt(offerSdp);
            VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] offer_h264_pt=" << int(sess->payloadType);
        }

        // 建立发送视频轨（H264/PT=96）
        

        std::mutex lmu; std::condition_variable lcv; bool haveLocal=false; std::string localSdp;
        pc->onLocalDescription([&](rtc::Description desc){
            if (desc.type() == rtc::Description::Type::Answer) {
                std::unique_lock<std::mutex> lk(lmu); localSdp = std::string(desc);
                haveLocal = true; lcv.notify_all();
                VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
                    << "[WHEP] onLocalDescription Answer sid=" << sid << " sdp_len=" << localSdp.size();
            }
        });
        pc->onGatheringStateChange([&](rtc::PeerConnection::GatheringState g){ if (g == rtc::PeerConnection::GatheringState::Complete) { VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc") << "[WHEP] ICE gathering complete sid=" << sid; std::unique_lock<std::mutex> lk(lmu); lcv.notify_all(); } });
        pc->onStateChange([sess](rtc::PeerConnection::State st){
            if (st==rtc::PeerConnection::State::Connected) {
                sess->pcConnected = true; sess->lastActive = std::chrono::steady_clock::now();
                VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pc connected sid=" << sess->sid;
            }
        });

        // 设置远端与生成本地 Answer
        rtc::Description remote(offerSdp, rtc::Description::Type::Offer);
        pc->setRemoteDescription(remote);
        // Add sender (sendonly, H264/PT from Offer) after setting remote, before creating Answer
        rtc::Description::Video vdesc("video");
        vdesc.setDirection(rtc::Description::Direction::SendOnly);
        vdesc.addH264Codec(sess->payloadType, rtc::DEFAULT_H264_VIDEO_PROFILE);
        vdesc.addSSRC(sess->ssrc, std::string("va"), std::string("stream1"), std::string("video1"));
        sess->videoTrack = pc->addTrack(vdesc);
        attachMediaHandlers(*sess);
        try { if (sess->videoTrack) sess->videoTrack->onOpen([sid]{ VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] track open sid=" << sid; }); } catch(...) {}
        // Now create Answer
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
            VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc")
                << "[WHEP] createSession no local SDP generated sid=" << sid;
            return 500;
        }

        // 注册会话
        // Inject common H.264 fmtp parameters into Answer to improve browser decoder compatibility
        auto inject_h264_fmtp = [](const std::string& sdp) -> std::string {
            std::istringstream iss(sdp);
            std::vector<std::string> lines;
            lines.reserve(128);
            std::string line;
            while (std::getline(iss, line)) {
                if (!line.empty() && line.back() == '\r') line.pop_back();
                lines.push_back(line);
            }
            // Find H264 payload type
            std::string pt;
            int rtpmapIdx = -1;
            int mVideoStart = -1;
            int mVideoEnd = static_cast<int>(lines.size());
            for (size_t i = 0; i < lines.size(); ++i) {
                const std::string& L = lines[i];
                if (mVideoStart < 0 && L.rfind("m=video", 0) == 0) {
                    mVideoStart = static_cast<int>(i);
                    // find end of this media section
                    for (size_t k = i + 1; k < lines.size(); ++k) {
                        if (lines[k].rfind("m=", 0) == 0) { mVideoEnd = static_cast<int>(k); break; }
                    }
                }
                if (L.rfind("a=rtpmap:", 0) == 0 && L.find("H264/90000") != std::string::npos) {
                    size_t c = L.find(':');
                    size_t sp = L.find(' ', c == std::string::npos ? 0 : c + 1);
                    if (c != std::string::npos && sp != std::string::npos && sp > c + 1) {
                        pt = L.substr(c + 1, sp - (c + 1));
                        rtpmapIdx = static_cast<int>(i);
                        break;
                    }
                }
            }
            if (pt.empty()) {
                return sdp; // nothing to do
            }
            // Build fmtp line
            const std::string wanted = std::string("a=fmtp:") + pt + " profile-level-id=42e01f;packetization-mode=1;level-asymmetry-allowed=1";
            bool replaced = false;
            for (size_t i = 0; i < lines.size(); ++i) {
                const std::string& L = lines[i];
                if (L.rfind("a=fmtp:" + pt, 0) == 0) {
                    lines[i] = wanted;
                    replaced = true;
                    break;
                }
            }
            if (!replaced && rtpmapIdx >= 0) {
                // Insert right after rtpmap
                lines.insert(lines.begin() + rtpmapIdx + 1, wanted);
                if (mVideoEnd >= rtpmapIdx + 1) ++mVideoEnd;
            }
            // Rebuild SDP with CRLF
            std::ostringstream oss;
            for (const auto& s : lines) oss << s << "\r\n";
            return oss.str();
        };

        outSid = sid;
        outAnswerSdp = inject_h264_fmtp(localSdp);
        {
            std::string snipA = outAnswerSdp.substr(0, 200);
            for (auto& ch : snipA) { if (ch=='\r' || ch=='\n') ch=' '; }
            VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc") << "[WHEP] answer_head=" << snipA;
        }
        // Analyze Answer SDP details for troubleshooting
        {
            std::istringstream iss(outAnswerSdp);
            std::string line; std::string cur_mid; std::string video_mid;
            std::string dir; bool has_msid=false; std::string h264_pt; bool has_fmtp=false; bool has_pmode=false; bool has_plid=false; bool has_sprop=false;
            while (std::getline(iss, line)) {
                if (!line.empty() && line.back()=='\r') line.pop_back();
                if (line.rfind("m=video", 0)==0) { cur_mid.clear(); dir.clear(); }
                if (line.rfind("a=mid:", 0)==0) { cur_mid = line.substr(6); if (video_mid.empty()) video_mid = cur_mid; }
                if (line == "a=sendonly" || line=="a=recvonly" || line=="a=inactive" || line=="a=sendrecv") { if (dir.empty()) dir = line.substr(2); }
                if (line.rfind("a=msid:", 0)==0) has_msid = true;
                // Also recognize SSRC-based msid binding: a=ssrc:<ssrc> msid:<stream> <track>
                if (!has_msid && line.rfind("a=ssrc:", 0)==0 && line.find(" msid:") != std::string::npos) has_msid = true;
                if (line.rfind("a=rtpmap:", 0)==0 && line.find("H264/90000")!=std::string::npos) {
                    size_t c = line.find(':'); size_t sp = line.find(' ', (c==std::string::npos?0:c+1));
                    if (c!=std::string::npos && sp!=std::string::npos && sp>c+1) h264_pt = line.substr(c+1, sp-(c+1));
                }
                if (!h264_pt.empty() && line.rfind(std::string("a=fmtp:")+h264_pt, 0)==0) {
                    has_fmtp = true;
                    if (line.find("packetization-mode=1")!=std::string::npos) has_pmode = true;
                    if (line.find("profile-level-id=")!=std::string::npos) has_plid = true;
                    if (line.find("sprop-parameter-sets=")!=std::string::npos) has_sprop = true;
                }
            }
            VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
                << "[WHEP] sdp_check mid=" << (video_mid.empty()?"?":video_mid)
                << " dir=" << (dir.empty()?"?":dir)
                << " h264_pt=" << (h264_pt.empty()?"?":h264_pt)
                << " fmtp=" << (has_fmtp?"1":"0")
                << " pmode1=" << (has_pmode?"1":"0")
                << " plid=" << (has_plid?"1":"0")
                << " sprop=" << (has_sprop?"1":"0")
                << " msid=" << (has_msid?"1":"0")
                << " used_pt=" << int(sess->payloadType);

        }
        // Register session for this streamKey so frames can be delivered
        {
            std::lock_guard<std::mutex> g(mu_);
            bySid_[sid] = sess;
            indexByStream_.emplace(streamKey, sid);
        }
        VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc")
            << "[WHEP] createSession ok sid=" << sid << " answer_len=" << outAnswerSdp.size();
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
        VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc")
            << "[WHEP] patch sid=" << sid << " frag_len=" << sdpFrag.size() << " has_cand=" << (!cand.empty()) << " mid='" << mid << "'";
        if (!cand.empty()) {
            rtc::Candidate cnd(cand, mid);
            sess->pc->addRemoteCandidate(cnd);
        }
        return 204;
    } catch (...) {
        VA_LOG_C(::va::core::LogLevel::Warn, "transport.webrtc") << "[WHEP] patch exception sid=" << sid;
        return 400;
    }
}

int WhepSessionManager::deleteSession(const std::string& sid) {
    VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] delete sid=" << sid;
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
    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 3000)
        << "[WHEP] feedFrame stream='" << streamKey << "' sessions=" << targets.size() << " frame_bytes=" << data.size();
    if (targets.empty()) return;

    // Simple AnnexB IDR detector
    auto has_idr = [](const std::vector<uint8_t>& buf) -> bool {
        size_t i = 0; const size_t n = buf.size();
        while (i + 4 < n) {
            // find start code 0x000001 or 0x00000001
            if (buf[i]==0x00 && buf[i+1]==0x00 && ((buf[i+2]==0x01) || (buf[i+2]==0x00 && buf[i+3]==0x01))) {
                size_t j = (buf[i+2]==0x01) ? (i+3) : (i+4);
                if (j < n) {
                    uint8_t nal = buf[j] & 0x1F; // H.264 NAL type
                    if (nal == 5) return true; // IDR
                }
                i = j + 1; continue;
            }
            ++i;
        }
        return false;
    };

    auto cache_sps_pps = [](const std::vector<uint8_t>& buf, std::vector<uint8_t>& out_sps, std::vector<uint8_t>& out_pps) {
        size_t i = 0; const size_t n = buf.size();
        auto next_sc = [&](size_t pos){
            for (size_t k = pos; k + 3 < n; ++k) {
                if (buf[k]==0x00 && buf[k+1]==0x00 && ((buf[k+2]==0x01) || (buf[k+2]==0x00 && buf[k+3]==0x01))) return k;
            }
            return n;
        };
        while (i + 4 < n) {
            // find start code
            size_t sc = next_sc(i);
            if (sc >= n) break;
            size_t hdr = (buf[sc+2]==0x01)? (sc+3) : (sc+4);
            if (hdr >= n) break;
            uint8_t nal = buf[hdr] & 0x1F;
            size_t next = next_sc(hdr);
            if (nal == 7) { // SPS
                out_sps.assign(buf.begin()+sc, (next<=n? buf.begin()+next : buf.end()));
            } else if (nal == 8) { // PPS
                out_pps.assign(buf.begin()+sc, (next<=n? buf.begin()+next : buf.end()));
            }
            i = (next < n)? next : n;
        }
    };

    for (auto& kv : targets) {
        auto sess = kv.second;
        if (!sess || !sess->videoTrack) continue;
        if (!sess->pcConnected) {
            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000) << "[WHEP] waiting pc connected stream='" << streamKey << "' sid=" << kv.first;
            continue;
        }
        bool closed = false; try { closed = sess->videoTrack->isClosed(); } catch (...) { closed = true; }
        if (closed) { sess->closed = true; continue; }
        bool open = false; try { open = sess->videoTrack->isOpen(); } catch (...) { open = false; }
        if (!open) {
            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000)
                << "[WHEP] waiting track open stream='" << streamKey << "' sid=" << kv.first;
            continue;
        }

        // Copy + normalize
        std::vector<uint8_t> h264 = data;
        ensure_annexb(h264);
        // Update SPS/PPS cache from this frame
        cache_sps_pps(h264, sess->last_sps, sess->last_pps);
        // Before the first IDR, skip sending to ensure decoders can start cleanly
        if (!sess->started) {
            if (has_idr(h264)) {
                sess->started = true;
                VA_LOG_C(::va::core::LogLevel::Debug, "transport.webrtc") << "[WHEP] first IDR observed sid=" << kv.first;
                // If we have cached SPS/PPS, prepend them to ensure decoder config
                if (!sess->last_sps.empty()) {
                    rtc::binary s; s.resize(sess->last_sps.size()); std::memcpy(s.data(), sess->last_sps.data(), sess->last_sps.size());
                    rtc::FrameInfo fi(sess->ts90);
                    try { sess->videoTrack->sendFrame(std::move(s), fi); } catch (...) {}
                    sess->ts90 += (90000u / 30u);
                }
                if (!sess->last_pps.empty()) {
                    rtc::binary p; p.resize(sess->last_pps.size()); std::memcpy(p.data(), sess->last_pps.data(), sess->last_pps.size());
                    rtc::FrameInfo fi2(sess->ts90);
                    try { sess->videoTrack->sendFrame(std::move(p), fi2); } catch (...) {}
                    sess->ts90 += (90000u / 30u);
                }
            } else {
                // drop till first IDR
                VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000)
                    << "[WHEP] waiting for IDR stream='" << streamKey << "' sid=" << kv.first;
                continue;
            }
        }
        rtc::binary frame;
        frame.resize(h264.size());
        std::memcpy(frame.data(), h264.data(), h264.size());
        rtc::FrameInfo finfo(sess->ts90);
        try { sess->videoTrack->sendFrame(std::move(frame), finfo); }
        catch (const std::exception& ex) {
            // 某些浏览器在 track 尚未完全 open 阶段会抛出 "Track is not open"，保持会话并等待下一轮
            VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first << " err=" << ex.what();
            continue;
        }
        catch (...) {
            VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first;
            continue;
        }
        sess->ts90 += (90000u / 30u);
        sess->lastActive = std::chrono::steady_clock::now();
    }
    // Cleanup closed sessions for this streamKey to avoid map growth and needless scans
    {
        std::lock_guard<std::mutex> g(mu_);
        for (auto it = indexByStream_.begin(); it != indexByStream_.end();) {
            if (it->first != streamKey) { ++it; continue; }
            auto sit = bySid_.find(it->second);
            bool drop = (sit == bySid_.end()) || !sit->second || sit->second->closed;
            if (drop) {
                it = indexByStream_.erase(it);
                if (sit != bySid_.end()) bySid_.erase(sit);
            } else {
                ++it;
            }
        }
    }
}

} // namespace va::media

