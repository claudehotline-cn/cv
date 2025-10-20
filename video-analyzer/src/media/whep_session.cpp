// WHEP session manager (stable minimal send path aligned with 8090)
#include "media/whep_session.hpp"
#include "core/logger.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <random>
#include <sstream>
#include <unordered_set>

namespace va::media {

// Convert AVCC to AnnexB if needed
static inline void ensure_annexb(std::vector<uint8_t>& buf) {
  if (buf.size() < 4) return;
  auto has_start_code = [&](size_t from)->bool{
    for (size_t i = from; i + 3 < buf.size(); ++i) {
      if (buf[i]==0x00 && buf[i+1]==0x00 && (buf[i+2]==0x01 || (i+3<buf.size() && buf[i+2]==0x00 && buf[i+3]==0x01))) return true;
    }
    return false;
  };
  // If buffer already contains AnnexB start code (00 00 01 or 00 00 00 01), do nothing
  if (has_start_code(0)) return;
  // Try AVCC length-prefixed conversion
  std::vector<uint8_t> out; out.reserve(buf.size()+16);
  size_t pos = 0; const uint8_t sc[4] = {0,0,0,1};
  while (pos + 4 <= buf.size()) {
    uint32_t len = (uint32_t(buf[pos])<<24) | (uint32_t(buf[pos+1])<<16) | (uint32_t(buf[pos+2])<<8) | (uint32_t(buf[pos+3]));
    pos += 4;
    if (len == 0 || pos + len > buf.size()) { out.clear(); break; }
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
  double pace_bps = 0.0; // default OFF
  if (const char* pv = std::getenv("VA_WHEP_PACE_BPS"); pv && *pv) {
    try { pace_bps = std::stod(pv); } catch (...) { pace_bps = 0.0; }
  }
  if (s.videoTrack) {
    s.videoTrack->setMediaHandler(s.h264pack);
    if (pace_bps > 0.0) {
      s.pacing = std::make_shared<rtc::PacingHandler>(pace_bps, std::chrono::milliseconds(8));
      s.videoTrack->chainMediaHandler(s.pacing);
      VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pacing enabled bps=" << pace_bps;
    } else {
      VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pacing disabled";
    }
  }
}

static uint8_t parse_offer_h264_pt(const std::string& sdp) {
  std::istringstream iss(sdp); std::string line;
  while (std::getline(iss, line)) {
    if (!line.empty() && line.back()=='\r') line.pop_back();
    if (line.rfind("a=rtpmap:", 0)==0 && line.find("H264/90000")!=std::string::npos) {
      size_t c = line.find(':'); size_t sp = line.find(' ', (c==std::string::npos?0:c+1));
      if (c!=std::string::npos && sp!=std::string::npos && sp>c+1) {
        try { int v = std::stoi(line.substr(c+1, sp-(c+1))); if (v>=0 && v<=127) return uint8_t(v); } catch(...) {}
      }
    }
  }
  return uint8_t(96);
}

static std::string parse_offer_mid(const std::string& sdp) {
  std::istringstream iss(sdp); std::string line; bool inVideo=false; std::string mid;
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

    // Apply remote offer
    try { rtc::Description offer(offerSdp, rtc::Description::Type::Offer); pc->setRemoteDescription(offer); }
    catch (const std::exception& ex) { VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] setRemoteDescription ex: " << ex.what(); return 400; }
    catch (...) { VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] setRemoteDescription unknown"; return 400; }

    // Add local sendonly video track on offer's mid
    sess->mid = parse_offer_mid(offerSdp);
    {
      rtc::Description::Video vdesc(sess->mid);
      vdesc.setDirection(rtc::Description::Direction::SendOnly);
      vdesc.addH264Codec(sess->payloadType, rtc::DEFAULT_H264_VIDEO_PROFILE);
      vdesc.addSSRC(sess->ssrc, std::string("va"), std::string("stream1"), std::string("video1"));
      sess->videoTrack = pc->addTrack(vdesc);
      attachMediaHandlers(*sess);
      try { if (sess->videoTrack) sess->videoTrack->onOpen([sess, sid]{ sess->trackOpen.store(true); VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] track open sid=" << sid; }); } catch (...) {}
    }

    pc->onStateChange([sess](rtc::PeerConnection::State st){ if (st == rtc::PeerConnection::State::Connected) { sess->pcConnected.store(true); sess->lastActive = std::chrono::steady_clock::now(); VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pc connected sid=" << sess->sid; } });

    // Create local answer
    try { auto ans = pc->createAnswer(); outAnswerSdp = ans.generateSdp(); }
    catch (const std::exception& ex) { VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] createAnswer ex: " << ex.what(); return 500; }
    catch (...) { VA_LOG_C(::va::core::LogLevel::Error, "transport.webrtc") << "[WHEP] createAnswer unknown"; return 500; }
    if (outAnswerSdp.empty()) return 409;

    // Patch Answer SDP: ensure H264 fmtp has packetization-mode=1 (non-interleaved)
    // Some receivers treat pmode=0 rigidly and may mishandle FU-A; aligning to pmode=1 improves P-frame continuity.
    {
      std::istringstream iss(outAnswerSdp);
      std::vector<std::string> lines; lines.reserve(128);
      std::string line; std::string h264_pt; int rtpmapIdx=-1; int mVideoStart=-1; int mVideoEnd=-1;
      while (std::getline(iss, line)) { if (!line.empty() && line.back()=='\r') line.pop_back(); lines.push_back(line); }
      for (size_t i=0;i<lines.size();++i) {
        const std::string& L = lines[i];
        if (mVideoStart<0 && L.rfind("m=video",0)==0) { mVideoStart=(int)i; for (size_t k=i+1;k<lines.size();++k){ if (lines[k].rfind("m=",0)==0){ mVideoEnd=(int)k; break; } } if (mVideoEnd<0) mVideoEnd=(int)lines.size(); }
        if (L.rfind("a=rtpmap:",0)==0 && L.find("H264/90000")!=std::string::npos) {
          size_t c=L.find(':'), sp=L.find(' ', (c==std::string::npos?0:c+1)); if (c!=std::string::npos && sp!=std::string::npos && sp>c+1) { h264_pt=L.substr(c+1, sp-(c+1)); rtpmapIdx=(int)i; }
        }
      }
      if (!h264_pt.empty() && mVideoStart>=0) {
        int fmtpIdx=-1;
        for (int i=mVideoStart; i<mVideoEnd && i<(int)lines.size(); ++i) {
          if (lines[i].rfind(std::string("a=fmtp:")+h264_pt,0)==0) { fmtpIdx=i; break; }
        }
        auto ensure_pmode1 = [&](const std::string& src)->std::string{
          // a=fmtp:<pt> <params...>
          size_t sp = src.find(' ');
          std::string prefix = (sp==std::string::npos)? src : src.substr(0, sp);
          std::string params = (sp==std::string::npos)? std::string() : src.substr(sp+1);
          // split by ';'
          std::vector<std::string> kvs; std::string cur; for (char ch : params){ if (ch==';'){ if(!cur.empty()) kvs.push_back(cur); cur.clear(); } else { cur.push_back(ch);} } if(!cur.empty()) kvs.push_back(cur);
          auto trim = [](std::string& s){ while(!s.empty() && (s.front()==' '||s.front()=='\t')) s.erase(s.begin()); while(!s.empty() && (s.back()==' '||s.back()=='\t')) s.pop_back(); };
          bool has_pmode=false, has_lasym=false;
          for (auto& k : kvs){ std::string t=k; trim(t); auto p=t.find('='); std::string key=(p==std::string::npos)? t : t.substr(0,p); for (auto& c:key) c=char(std::tolower(c)); if (key=="packetization-mode") has_pmode=true; if (key=="level-asymmetry-allowed") has_lasym=true; }
          if (!has_pmode) kvs.push_back("packetization-mode=1");
          if (!has_lasym) kvs.push_back("level-asymmetry-allowed=1");
          std::ostringstream os; os<<prefix; if(!kvs.empty()){ os<<' '; for(size_t i=0;i<kvs.size();++i){ if(i) os<<';'; os<<kvs[i]; } }
          return os.str();
        };
        if (fmtpIdx>=0) { lines[fmtpIdx] = ensure_pmode1(lines[fmtpIdx]); }
        else if (rtpmapIdx>=0) { lines.insert(lines.begin()+rtpmapIdx+1, std::string("a=fmtp:")+h264_pt+" packetization-mode=1;level-asymmetry-allowed=1"); if (mVideoEnd>rtpmapIdx+1) ++mVideoEnd; }
        std::ostringstream os; for (size_t i=0;i<lines.size();++i){ os<<lines[i]<<"\r\n"; } outAnswerSdp=os.str();
      }
    }

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
  } catch (...) { return 500; }
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
    if (!cand.empty()) { rtc::Candidate cnd(cand, mid); sess->pc->addRemoteCandidate(cnd); }
    return 204;
  } catch (...) { VA_LOG_C(::va::core::LogLevel::Warn, "transport.webrtc") << "[WHEP] patch exception sid=" << sid; return 400; }
}

int WhepSessionManager::deleteSession(const std::string& sid) {
  VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] delete sid=" << sid;
  std::shared_ptr<Session> sess;
  {
    std::lock_guard<std::mutex> g(mu_);
    auto it = bySid_.find(sid); if (it == bySid_.end()) return 404; sess = it->second;
    bySid_.erase(it);
    for (auto i = indexByStream_.begin(); i != indexByStream_.end();) { if (i->second == sid) i = indexByStream_.erase(i); else ++i; }
  }
  try { if (sess->videoTrack) { try { sess->videoTrack->close(); } catch (...) {} } if (sess->pc) { try { sess->pc->close(); } catch (...) {} } } catch (...) {}
  return 204;
}

void WhepSessionManager::feedFrame(const std::string& streamKey, const std::vector<uint8_t>& data) {
  // Build targets
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
    add_range(streamKey);
    auto pos = streamKey.find(':'); if (pos != std::string::npos) add_range(streamKey.substr(0, pos));
    if (!targets.empty()) {
      std::unordered_set<std::string> seen; std::vector<std::pair<std::string, std::shared_ptr<Session>>> uniq; uniq.reserve(targets.size());
      for (auto& kv : targets) { if (seen.insert(kv.first).second) uniq.emplace_back(kv); }
      targets.swap(uniq);
    }
  }
  if (targets.empty()) return;

  // Small helper: cache latest SPS/PPS in AnnexB
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

  // Detect if current AnnexB buffer contains an IDR slice
  auto has_idr = [](const std::vector<uint8_t>& buf)->bool{
    size_t i = 0, n = buf.size();
    while (i + 4 < n) {
      // find 0x000001 or 0x00000001
      if (buf[i]==0x00 && buf[i+1]==0x00 && ((buf[i+2]==0x01) || (buf[i+2]==0x00 && buf[i+3]==0x01))) {
        size_t j = (buf[i+2]==0x01)? (i+3) : (i+4);
        if (j < n) {
          uint8_t nal = buf[j] & 0x1F;
          if (nal == 5) return true; // IDR
        }
        i = j + 1; continue;
      }
      ++i;
    }
    return false;
  };

  for (auto& kv : targets) {
    auto sess = kv.second; if (!sess || !sess->videoTrack) continue;
    if (!sess->pcConnected.load()) continue;
    bool closed=false; try { closed = sess->videoTrack->isClosed(); } catch (...) { closed = true; }
    if (closed) { sess->closed.store(true); continue; }
    bool open=false; try { open = sess->videoTrack->isOpen(); } catch (...) { open = false; }
    if (!open) continue;

    // Normalize + update SPS/PPS cache
    std::vector<uint8_t> h264 = data; ensure_annexb(h264); cache_sps_pps(h264, sess->last_sps, sess->last_pps);
    const bool idr = has_idr(h264);

    // Decide timestamp for this output frame (fixed 30fps)
    const uint32_t next_ts = sess->ts90 + (90000u/30u);

    // If first frame and we still lack SPS/PPS and it's not IDR, wait for IDR/SPS/PPS to avoid undecodable P 帧
    if (!sess->started.load() && (sess->last_sps.empty() || sess->last_pps.empty()) && !idr) {
      continue;
    }

    // Build a single access unit per frame and send exactly once with marker at the end.
    // For IDR, prepend cached SPS/PPS to the same access unit to maximize decoder compatibility.
    std::vector<uint8_t> au;
    if (idr) {
      if (!sess->last_sps.empty()) { au.insert(au.end(), sess->last_sps.begin(), sess->last_sps.end()); }
      if (!sess->last_pps.empty()) { au.insert(au.end(), sess->last_pps.begin(), sess->last_pps.end()); }
      sess->started.store(true);
    }
    au.insert(au.end(), h264.begin(), h264.end());

    rtc::binary frame; frame.resize(au.size()); std::memcpy(frame.data(), au.data(), au.size());
    rtc::FrameInfo finfo(next_ts);
    try { sess->videoTrack->sendFrame(std::move(frame), finfo); }
    catch (const std::exception& ex) { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first << " err=" << ex.what(); continue; }
    catch (...) { VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000) << "[WHEP] sendFrame ex sid=" << kv.first; continue; }
    sess->ts90 = next_ts;
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
