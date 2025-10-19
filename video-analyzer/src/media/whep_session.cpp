// WHEP session manager implementation
#include "media/whep_session.hpp"
#include "core/logger.hpp"

#include <algorithm>
#include <cctype>
#include <cstring>
#include <random>
#include <sstream>
#include <unordered_set>

namespace va::media {

// Convert AVCC (length-prefixed) to AnnexB if needed
static inline void ensure_annexb(std::vector<uint8_t>& buf) {
  if (buf.size() < 4) return;
  if (buf[0]==0x00 && buf[1]==0x00 && buf[2]==0x00 && buf[3]==0x01) return;
  std::vector<uint8_t> out; out.reserve(buf.size()+16);
  size_t pos = 0;
  const uint8_t sc[4] = {0,0,0,1};
  while (pos + 4 <= buf.size()) {
    uint32_t len = (uint32_t(buf[pos])<<24) | (uint32_t(buf[pos+1])<<16) | (uint32_t(buf[pos+2])<<8) | (uint32_t(buf[pos+3]));
    pos += 4;
    if (len == 0 || pos + len > buf.size()) return; // not AVCC, bail out
    out.insert(out.end(), sc, sc+4);
    out.insert(out.end(), buf.begin()+pos, buf.begin()+pos+len);
    pos += len;
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
  uint8_t pt = s.payloadType ? s.payloadType : uint8_t(96);
  s.rtpCfg = std::make_shared<rtc::RtpPacketizationConfig>(s.ssrc, std::string("va"), pt, rtc::H264RtpPacketizer::ClockRate);
  s.h264pack = std::make_shared<rtc::H264RtpPacketizer>(rtc::NalUnit::Separator::StartSequence, s.rtpCfg, maxFrag);
  VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] media handler set pt=" << int(pt) << " maxFrag=" << maxFrag;
  // Optional pacing controlled via VA_WHEP_PACE_BPS (bps)
  double pace_bps = 0.0;
  if (const char* pv = std::getenv("VA_WHEP_PACE_BPS"); pv && *pv) {
    try { pace_bps = std::stod(pv); } catch (...) { pace_bps = 0.0; }
  }
  if (s.videoTrack) {
    s.videoTrack->setMediaHandler(s.h264pack);
    if (pace_bps > 0.0) {
      s.pacing = std::make_shared<rtc::PacingHandler>(pace_bps, std::chrono::milliseconds(8));
      s.videoTrack->chainMediaHandler(s.pacing);
      VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pacing enabled bps=" << pace_bps;
    }
  }
}

static uint8_t parse_offer_h264_pt(const std::string& sdp) {
  std::istringstream iss(sdp);
  std::string line;
  while (std::getline(iss, line)) {
    if (!line.empty() && line.back()=='\r') line.pop_back();
    if (line.rfind("a=rtpmap:", 0)==0 && line.find("H264/90000")!=std::string::npos) {
      size_t c = line.find(':'); size_t sp = line.find(' ', (c==std::string::npos?0:c+1));
      if (c!=std::string::npos && sp!=std::string::npos && sp>c+1) {
        try { int v = std::stoi(line.substr(c+1, sp-(c+1))); if (v>=0 && v<=127) return uint8_t(v); } catch (...) {}
      }
    }
  }
  return uint8_t(96);
}

static std::string parse_offer_mid(const std::string& sdp) {
  std::istringstream iss(sdp);
  std::string line; bool inVideo=false; std::string mid;
  while (std::getline(iss, line)) {
    if (!line.empty() && line.back()=='\r') line.pop_back();
    if (line.rfind("m=video", 0)==0) { inVideo = true; continue; }
    if (line.rfind("m=", 0)==0 && line.rfind("m=video", 0)!=0) { inVideo = false; }
    if (inVideo && line.rfind("a=mid:", 0)==0) { mid = line.substr(6); break; }
  }
  return mid.empty()? std::string("0") : mid;
}

int WhepSessionManager::createSession(const std::string& streamKey,
                                      const std::string& offerSdp,
                                      std::string& outAnswerSdp,
                                      std::string& outSid) {
  try {
    rtc::Configuration cfg;
    cfg.portRangeBegin = 10000; cfg.portRangeEnd = 10100;
    if (const char* bind = std::getenv("VA_ICE_BIND")) { if (bind && *bind) cfg.bindAddress = std::string(bind); }

    auto pc = std::make_shared<rtc::PeerConnection>(cfg);
    auto sid = genSid();
    VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] createSession sid=" << sid << " stream='" << streamKey << "' offer_len=" << offerSdp.size();

    auto sess = std::make_shared<Session>();
    sess->sid = sid;
    sess->streamKey = streamKey;
    sess->ssrc = std::random_device{}();
    sess->pc = pc;
    sess->lastActive = std::chrono::steady_clock::now();
    sess->createdAt  = sess->lastActive;
    sess->payloadType = parse_offer_h264_pt(offerSdp);

    // Apply remote Offer
    try {
      rtc::Description offer(offerSdp, rtc::Description::Type::Offer);
      pc->setRemoteDescription(offer);
    } catch (const std::exception& ex) {
      VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] setRemoteDescription exception sid=" << sid << " err=" << ex.what();
      return 400;
    } catch (...) {
      VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] setRemoteDescription unknown error sid=" << sid;
      return 400;
    }

    // Add local sendonly video track using Offer mid
    sess->mid = parse_offer_mid(offerSdp);
    {
      rtc::Description::Video vdesc(sess->mid);
      vdesc.setDirection(rtc::Description::Direction::SendOnly);
      vdesc.addH264Codec(sess->payloadType, rtc::DEFAULT_H264_VIDEO_PROFILE);
      vdesc.addSSRC(sess->ssrc, std::string("va"), std::string("stream1"), std::string("video1"));
      sess->videoTrack = pc->addTrack(vdesc);
      attachMediaHandlers(*sess);
      try {
        if (sess->videoTrack) sess->videoTrack->onOpen([sess, sid]{ sess->trackOpen.store(true); VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] track open sid=" << sid; });
      } catch (...) {}
    }

    pc->onStateChange([sess](rtc::PeerConnection::State st){
      if (st == rtc::PeerConnection::State::Connected) {
        sess->pcConnected.store(true);
        sess->lastActive = std::chrono::steady_clock::now();
        VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pc connected sid=" << sess->sid;
      }
    });

    // Create Answer
    try {
      auto ans = pc->createAnswer();
      outAnswerSdp = ans.generateSdp();
    } catch (const std::exception& ex) {
      VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] createAnswer exception sid=" << sid << " err=" << ex.what();
      return 500;
    } catch (...) {
      VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] createAnswer unknown error sid=" << sid;
      return 500;
    }
    if (outAnswerSdp.empty()) {
      VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] no local SDP generated sid=" << sid;
      return 409;
    }

    // Register session
    {
      std::lock_guard<std::mutex> g(mu_);
      bySid_[sid] = sess;
      indexByStream_.emplace(streamKey, sid);
    }
    outSid = sid;
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
    auto it = bySid_.find(sid);
    if (it == bySid_.end()) return 404;
    sess = it->second;
  }
  if (!sess || !sess->pc) return 404;
  try {
    std::string cand; std::string mid("0");
    auto rtrim = [](std::string& s){ if (!s.empty() && s.back()=='\r') s.pop_back(); };
    std::istringstream iss(sdpFrag); std::string line;
    while (std::getline(iss, line)) {
      rtrim(line);
      if (line.rfind("a=candidate:", 0) == 0) { cand = line.substr(2); rtrim(cand); }
      if (line.rfind("a=mid:", 0) == 0) { mid = line.substr(6); rtrim(mid); }
    }
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
    for (auto i = indexByStream_.begin(); i != indexByStream_.end();) {
      if (i->second == sid) i = indexByStream_.erase(i); else ++i;
    }
  }
  try { if (sess->videoTrack) { try { sess->videoTrack->close(); } catch (...) {} } if (sess->pc) { try { sess->pc->close(); } catch (...) {} } } catch (...) {}
  return 204;
}

void WhepSessionManager::feedFrame(const std::string& streamKey, const std::vector<uint8_t>& data) {
  std::vector<std::pair<std::string, std::shared_ptr<Session>>> targets;
  {
    std::lock_guard<std::mutex> g(mu_);
    auto add_range = [&](const std::string& key){
      auto range = indexByStream_.equal_range(key);
      for (auto it = range.first; it != range.second; ++it) {
        const auto& sid = it->second;
        auto sit = bySid_.find(sid);
        if (sit != bySid_.end() && sit->second && !sit->second->closed) targets.emplace_back(sid, sit->second);
      }
    };
    // Collect both fullKey and baseKey, then de-duplicate
    add_range(streamKey);
    auto pos = streamKey.find(':'); if (pos != std::string::npos) add_range(streamKey.substr(0, pos));
    if (!targets.empty()) {
      std::unordered_set<std::string> seen; std::vector<std::pair<std::string, std::shared_ptr<Session>>> uniq; uniq.reserve(targets.size());
      for (auto& kv : targets) { if (seen.insert(kv.first).second) uniq.emplace_back(kv); }
      targets.swap(uniq);
    }
  }

  VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000) << "[WHEP] feedFrame stream='" << streamKey << "' sessions=" << targets.size() << " frame_bytes=" << data.size();
  if (targets.empty()) return;

  auto has_idr = [](const std::vector<uint8_t>& buf)->bool{
    size_t i=0, n=buf.size();
    while (i + 4 < n) {
      if (buf[i]==0x00 && buf[i+1]==0x00 && ((buf[i+2]==0x01) || (buf[i+2]==0x00 && buf[i+3]==0x01))) {
        size_t j = (buf[i+2]==0x01) ? (i+3) : (i+4);
        if (j < n) { uint8_t nal = buf[j] & 0x1F; if (nal == 5) return true; }
        i = j + 1; continue;
      }
      ++i;
    }
    return false;
  };

  auto cache_sps_pps = [](const std::vector<uint8_t>& buf, std::vector<uint8_t>& out_sps, std::vector<uint8_t>& out_pps){
    size_t i=0, n=buf.size();
    auto next_sc = [&](size_t p){ for (size_t k=p; k+3<n; ++k) { if (buf[k]==0x00 && buf[k+1]==0x00 && ((buf[k+2]==0x01) || (buf[k+2]==0x00 && buf[k+3]==0x01))) return k; } return n; };
    while (i + 4 < n) {
      size_t sc = next_sc(i); if (sc >= n) break;
      size_t hdr = (buf[sc+2]==0x01)? (sc+3) : (sc+4); if (hdr >= n) break;
      uint8_t nal = buf[hdr] & 0x1F; size_t next = next_sc(hdr);
      if (nal == 7) out_sps.assign(buf.begin()+sc, (next<=n? buf.begin()+next : buf.end()));
      else if (nal == 8) out_pps.assign(buf.begin()+sc, (next<=n? buf.begin()+next : buf.end()));
      i = (next < n) ? next : n;
    }
  };

  auto is_b_like = [](const std::vector<uint8_t>& buf)->bool{
    size_t i=0, n=buf.size();
    auto match_sc = [&](size_t p)->size_t{ if (p+3<=n && buf[p]==0 && buf[p+1]==0 && buf[p+2]==1) return 3; if (p+4<=n && buf[p]==0 && buf[p+1]==0 && buf[p+2]==0 && buf[p+3]==1) return 4; return 0; };
    while (i + 3 < n) {
      size_t sc = match_sc(i); if (!sc) { ++i; continue; }
      size_t nal_pos = i + sc; if (nal_pos >= n) return false;
      uint8_t h = buf[nal_pos]; uint8_t nal_ref_idc = (h >> 5) & 0x03; uint8_t nal_type = h & 0x1f;
      if (nal_type == 1) return nal_ref_idc == 0; // non-IDR VCL
      if (nal_type == 5) return false; // IDR
      i = nal_pos + 1;
    }
    return false;
  };

  for (auto& kv : targets) {
    auto sess = kv.second; if (!sess || !sess->videoTrack) continue;
    if (!sess->pcConnected.load()) { VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000) << "[WHEP] waiting pc connected stream='" << streamKey << "' sid=" << kv.first; continue; }
    bool closed=false; try { closed = sess->videoTrack->isClosed(); } catch (...) { closed = true; }
    if (closed) { sess->closed.store(true); continue; }
    bool open=false; try { open = sess->videoTrack->isOpen(); } catch (...) { open = false; }
    if (!open) { VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000) << "[WHEP] waiting track open stream='" << streamKey << "' sid=" << kv.first; continue; }

    std::vector<uint8_t> h264 = data; ensure_annexb(h264); cache_sps_pps(h264, sess->last_sps, sess->last_pps); if (is_b_like(h264)) continue;

    if (!sess->started.load()) {
      bool idr = has_idr(h264);
      auto now = std::chrono::steady_clock::now();
      static int fallback_ms = [](){ int v=500; if (const char* pv = std::getenv("VA_WHEP_FALLBACK_MS")) { try { v = std::stoi(pv); } catch(...) {} } if (v < 0) v = 0; return v; }();
      bool guardElapsed = (sess->createdAt.time_since_epoch().count() != 0) && ((now - sess->createdAt) > std::chrono::milliseconds(fallback_ms));
      if (idr || guardElapsed) {
        sess->started.store(true);
        if (!sess->last_sps.empty()) { rtc::binary s; s.resize(sess->last_sps.size()); std::memcpy(s.data(), sess->last_sps.data(), sess->last_sps.size()); rtc::FrameInfo fi(sess->ts90); try { sess->videoTrack->sendFrame(std::move(s), fi); } catch (...) {} sess->ts90 += (90000u/30u); }
        if (!sess->last_pps.empty()) { rtc::binary p; p.resize(sess->last_pps.size()); std::memcpy(p.data(), sess->last_pps.data(), sess->last_pps.size()); rtc::FrameInfo fi2(sess->ts90); try { sess->videoTrack->sendFrame(std::move(p), fi2); } catch (...) {} sess->ts90 += (90000u/30u); }
      } else {
        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "transport.webrtc", 2000) << "[WHEP] waiting for IDR stream='" << streamKey << "' sid=" << kv.first;
        continue;
      }
    }

    // Adaptive 90kHz timestamp step based on wall clock to smooth playback
    auto now = std::chrono::steady_clock::now();
    if (sess->lastSentAt.time_since_epoch().count() == 0) {
      sess->ts90 += (90000u/30u);
    } else {
      auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - sess->lastSentAt).count();
      if (ms < 1) ms = 1; // avoid 0 step
      // clamp to avoid large jumps on stalls (e.g., <= 200 ms)
      if (ms > 200) ms = 200;
      uint32_t step = static_cast<uint32_t>(ms * 90); // 90kHz
      sess->ts90 += step;
    }
    sess->lastSentAt = now;
    rtc::binary frame; frame.resize(h264.size()); std::memcpy(frame.data(), h264.data(), h264.size());
    rtc::FrameInfo finfo(sess->ts90);
    try { sess->videoTrack->sendFrame(std::move(frame), finfo); }
    catch (const std::exception& ex) { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first << " err=" << ex.what(); continue; }
    catch (...) { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first; continue; }
    sess->ts90 += (90000u/30u);
    sess->dbg_frames++; sess->dbg_bytes += h264.size(); sess->lastActive = std::chrono::steady_clock::now();
  }

  // Cleanup closed sessions for this streamKey
  {
    std::lock_guard<std::mutex> g(mu_);
    for (auto it = indexByStream_.begin(); it != indexByStream_.end();) {
      if (it->first != streamKey) { ++it; continue; }
      auto sit = bySid_.find(it->second);
      bool drop = (sit == bySid_.end()) || !sit->second || sit->second->closed;
      if (drop) { it = indexByStream_.erase(it); if (sit != bySid_.end()) bySid_.erase(sit); }
      else { ++it; }
    }
  }
}

} // namespace va::media
