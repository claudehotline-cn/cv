// WHEP session manager (stable minimal send path aligned with 8090)
#include "media/whep_session.hpp"
#include "core/logger.hpp"

#include <algorithm>
#include <cstdint>
#include <cstring>
#include <limits>
#include <optional>
#include <random>
#include <sstream>
#include <unordered_set>

namespace va::media {

// Convert AVCC (length-prefixed) to AnnexB (start-code prefixed) if needed.
// Robust to lengthSize=4/2/1; if already AnnexB, no-op.
static inline void ensure_annexb(std::vector<uint8_t>& buf) {
  if (buf.size() < 4) return;
  auto has_start_code = [&](size_t from)->bool{
    for (size_t i = from; i + 3 < buf.size(); ++i) {
      if (buf[i]==0x00 && buf[i+1]==0x00 && (buf[i+2]==0x01 || (i+3<buf.size() && buf[i+2]==0x00 && buf[i+3]==0x01))) return true;
    }
    return false;
  };
  if (has_start_code(0)) return; // already AnnexB

  auto try_convert = [&](int lenSize)->bool{
    if (!(lenSize==4 || lenSize==2 || lenSize==1)) return false;
    std::vector<uint8_t> out; out.reserve(buf.size() + 16);
    size_t pos = 0; const uint8_t sc[4] = {0,0,0,1};
    while (pos + size_t(lenSize) <= buf.size()) {
      uint32_t len = 0;
      if (lenSize == 4) {
        len = (uint32_t(buf[pos])<<24) | (uint32_t(buf[pos+1])<<16) | (uint32_t(buf[pos+2])<<8) | (uint32_t(buf[pos+3]));
      } else if (lenSize == 2) {
        len = (uint32_t(buf[pos])<<8) | (uint32_t(buf[pos+1]));
      } else { // lenSize == 1
        len = uint32_t(buf[pos]);
      }
      pos += size_t(lenSize);
      if (len == 0 || pos + size_t(len) > buf.size()) {
        out.clear();
        return false;
      }
      out.insert(out.end(), sc, sc+4);
      out.insert(out.end(), buf.begin()+pos, buf.begin()+pos+len);
      pos += size_t(len);
    }
    if (pos != buf.size()) return false; // trailing garbage -> not AVCC
    buf.swap(out);
    return true;
  };

  // Try common length sizes in order: 4, then 2, then 1
  if (try_convert(4)) return;
  if (try_convert(2)) return;
  (void)try_convert(1);
}

static inline size_t find_start_code(const std::vector<uint8_t>& buf, size_t from, size_t& sc_len) {
  const size_t n = buf.size();
  for (size_t i = from; i + 3 < n; ++i) {
    if (i + 4 <= n && buf[i]==0x00 && buf[i+1]==0x00 && buf[i+2]==0x00 && buf[i+3]==0x01) { sc_len = 4; return i; }
    if (buf[i]==0x00 && buf[i+1]==0x00 && buf[i+2]==0x01) { sc_len = 3; return i; }
  }
  sc_len = 0;
  return std::numeric_limits<size_t>::max();
}

static inline bool is_vcl_nal(int nal_type) {
  return nal_type >= 1 && nal_type <= 5;
}

static inline void nal_to_rbsp(const uint8_t* payload, size_t len, std::vector<uint8_t>& out) {
  out.clear();
  out.reserve(len);
  for (size_t i = 0; i < len; ++i) {
    if (i + 2 < len && payload[i]==0x00 && payload[i+1]==0x00 && payload[i+2]==0x03) {
      out.push_back(0x00);
      out.push_back(0x00);
      i += 2;
      continue;
    }
    out.push_back(payload[i]);
  }
}

class BitReader {
 public:
  explicit BitReader(const std::vector<uint8_t>& data) : data_(data) {}

  bool readBits(int n, uint32_t& out) {
    if (n < 0 || n > 32) return false;
    if (bitsRemaining() < static_cast<size_t>(n)) return false;
    out = 0;
    for (int i = 0; i < n; ++i) {
      size_t idx = (bitpos_ + i) >> 3;
      int shift = 7 - static_cast<int>((bitpos_ + i) & 7);
      uint32_t bit = (data_[idx] >> shift) & 0x01;
      out = (out << 1) | bit;
    }
    bitpos_ += static_cast<size_t>(n);
    return true;
  }

  bool readBit(uint32_t& bit) { return readBits(1, bit); }

  std::optional<uint32_t> readUE() {
    int leading_zero_bits = 0;
    while (true) {
      uint32_t bit = 0;
      if (!readBit(bit)) return std::nullopt;
      if (bit == 0) {
        ++leading_zero_bits;
      } else {
        break;
      }
    }
    uint32_t value = (1u << leading_zero_bits) - 1u;
    for (int i = 0; i < leading_zero_bits; ++i) {
      uint32_t bit = 0;
      if (!readBit(bit)) return std::nullopt;
      value = (value << 1) | bit;
    }
    return value;
  }

  std::optional<int32_t> readSE() {
    auto ue = readUE();
    if (!ue.has_value()) return std::nullopt;
    uint32_t code_num = ue.value();
    int32_t val = static_cast<int32_t>((code_num + 1) / 2);
    if ((code_num & 1) == 0) val = -val;
    return val;
  }

  bool skipBits(size_t n) {
    if (bitsRemaining() < n) return false;
    bitpos_ += n;
    return true;
  }

  size_t bitsRemaining() const {
    if (bitpos_ >= data_.size() * 8) return 0;
    return data_.size() * 8 - bitpos_;
  }

 private:
  const std::vector<uint8_t>& data_;
  size_t bitpos_{0};
};

static inline bool first_mb_is_zero(const uint8_t* payload, size_t len) {
  if (!payload || len == 0) return true;
  std::vector<uint8_t> rbsp;
  nal_to_rbsp(payload, len, rbsp);
  BitReader br(rbsp);
  auto first = br.readUE();
  if (!first.has_value()) return true;
  return first.value() == 0;
}

static bool skip_scaling_list(BitReader& br, int size) {
  int32_t lastScale = 8;
  int32_t nextScale = 8;
  for (int i = 0; i < size; ++i) {
    if (nextScale != 0) {
      auto delta = br.readSE();
      if (!delta.has_value()) return false;
      int32_t newScale = (lastScale + delta.value() + 256) % 256;
      nextScale = (newScale == 0) ? lastScale : newScale;
    }
    lastScale = nextScale;
  }
  return true;
}

struct SliceHeaderInfo {
  bool valid{false};
  bool first_mb_zero{true};
  bool is_idr{false};
  uint32_t frame_num{0};
  bool field_pic{false};
  bool has_poc_lsb{false};
  uint32_t pic_order_cnt_lsb{0};
  uint32_t pps_id{0};
  uint32_t sps_id{0};
};

static bool parse_sps(const uint8_t* payload, size_t len, H264SpsInfo& out) {
  if (!payload || len == 0) return false;
  std::vector<uint8_t> rbsp;
  nal_to_rbsp(payload, len, rbsp);
  if (rbsp.empty()) return false;
  BitReader br(rbsp);

  uint32_t profile_idc = 0;
  if (!br.readBits(8, profile_idc)) return false;
  uint32_t constraints = 0;
  if (!br.readBits(8, constraints)) return false;
  (void)constraints;
  uint32_t level_idc = 0;
  if (!br.readBits(8, level_idc)) return false;
  (void)level_idc;

  auto sps_id = br.readUE();
  if (!sps_id.has_value()) return false;

  H264SpsInfo info;
  info.id = sps_id.value();

  uint32_t chroma_format_idc = 1;
  if (profile_idc == 100 || profile_idc == 110 || profile_idc == 122 ||
      profile_idc == 244 || profile_idc == 44  || profile_idc == 83  ||
      profile_idc == 86  || profile_idc == 118 || profile_idc == 128 ||
      profile_idc == 138 || profile_idc == 139 || profile_idc == 134) {
    auto chroma = br.readUE();
    if (!chroma.has_value()) return false;
    chroma_format_idc = chroma.value();
    if (chroma_format_idc == 3) {
      uint32_t sep = 0;
      if (!br.readBits(1, sep)) return false;
      info.separate_colour_plane_flag = (sep != 0);
    }
    auto bit_depth_luma_minus8 = br.readUE();
    auto bit_depth_chroma_minus8 = br.readUE();
    if (!bit_depth_luma_minus8.has_value() || !bit_depth_chroma_minus8.has_value()) return false;
    uint32_t qpprime_y_zero_transform_bypass_flag = 0;
    if (!br.readBits(1, qpprime_y_zero_transform_bypass_flag)) return false;
    uint32_t scaling_matrix_present_flag = 0;
    if (!br.readBits(1, scaling_matrix_present_flag)) return false;
    if (scaling_matrix_present_flag) {
      int count = (chroma_format_idc == 3) ? 12 : 8;
      for (int i = 0; i < count; ++i) {
        uint32_t flag = 0;
        if (!br.readBits(1, flag)) return false;
        if (flag) {
          if (!skip_scaling_list(br, (i < 6) ? 16 : 64)) return false;
        }
      }
    }
  }

  auto log2_max_frame_num_minus4 = br.readUE();
  if (!log2_max_frame_num_minus4.has_value()) return false;
  info.log2_max_frame_num = static_cast<uint32_t>(log2_max_frame_num_minus4.value() + 4);

  auto poc_type = br.readUE();
  if (!poc_type.has_value()) return false;
  info.pic_order_cnt_type = poc_type.value();
  if (info.pic_order_cnt_type == 0) {
    auto log2_max_pic_order_cnt_lsb_minus4 = br.readUE();
    if (!log2_max_pic_order_cnt_lsb_minus4.has_value()) return false;
    info.log2_max_pic_order_cnt_lsb = static_cast<uint32_t>(log2_max_pic_order_cnt_lsb_minus4.value() + 4);
  } else if (info.pic_order_cnt_type == 1) {
    uint32_t delta_always_zero = 0;
    if (!br.readBits(1, delta_always_zero)) return false;
    info.delta_pic_order_always_zero_flag = (delta_always_zero != 0);
    auto offset_for_non_ref_pic = br.readSE();
    auto offset_for_top_to_bottom_field = br.readSE();
    if (!offset_for_non_ref_pic.has_value() || !offset_for_top_to_bottom_field.has_value()) return false;
    auto num_ref_frames_in_cycle = br.readUE();
    if (!num_ref_frames_in_cycle.has_value()) return false;
    for (uint32_t i = 0; i < num_ref_frames_in_cycle.value(); ++i) {
      auto val = br.readSE();
      if (!val.has_value()) return false;
    }
  } else {
    info.delta_pic_order_always_zero_flag = false;
  }

  auto max_num_ref_frames = br.readUE();
  if (!max_num_ref_frames.has_value()) return false;
  uint32_t gaps_in_frame_num_value_allowed_flag = 0;
  if (!br.readBits(1, gaps_in_frame_num_value_allowed_flag)) return false;
  (void)gaps_in_frame_num_value_allowed_flag;
  auto pic_width_in_mbs_minus1 = br.readUE();
  auto pic_height_in_map_units_minus1 = br.readUE();
  if (!pic_width_in_mbs_minus1.has_value() || !pic_height_in_map_units_minus1.has_value()) return false;

  uint32_t frame_mbs_only_flag = 1;
  if (!br.readBits(1, frame_mbs_only_flag)) return false;
  info.frame_mbs_only_flag = (frame_mbs_only_flag != 0);
  if (!info.frame_mbs_only_flag) {
    uint32_t mb_adaptive_frame_field_flag = 0;
    if (!br.readBits(1, mb_adaptive_frame_field_flag)) return false;
  }
  uint32_t direct_8x8_inference_flag = 0;
  if (!br.readBits(1, direct_8x8_inference_flag)) return false;
  uint32_t frame_cropping_flag = 0;
  if (!br.readBits(1, frame_cropping_flag)) return false;
  if (frame_cropping_flag) {
    auto frame_crop_left_offset = br.readUE();
    auto frame_crop_right_offset = br.readUE();
    auto frame_crop_top_offset = br.readUE();
    auto frame_crop_bottom_offset = br.readUE();
    if (!frame_crop_left_offset.has_value() || !frame_crop_right_offset.has_value() ||
        !frame_crop_top_offset.has_value() || !frame_crop_bottom_offset.has_value()) return false;
  }
  uint32_t vui_parameters_present_flag = 0;
  if (!br.readBits(1, vui_parameters_present_flag)) return false;
  if (vui_parameters_present_flag) {
    // We do not need VUI parameters for frame detection; ignore remaining bits.
  }

  info.valid = true;
  out = info;
  return true;
}

static bool parse_pps(const uint8_t* payload, size_t len, H264PpsInfo& out) {
  if (!payload || len == 0) return false;
  std::vector<uint8_t> rbsp;
  nal_to_rbsp(payload, len, rbsp);
  if (rbsp.empty()) return false;
  BitReader br(rbsp);

  auto pps_id = br.readUE();
  auto sps_id = br.readUE();
  if (!pps_id.has_value() || !sps_id.has_value()) return false;

  H264PpsInfo info;
  info.id = pps_id.value();
  info.sps_id = sps_id.value();

  uint32_t entropy_coding_mode_flag = 0;
  if (!br.readBits(1, entropy_coding_mode_flag)) return false;
  uint32_t pic_order_present_flag = 0;
  if (!br.readBits(1, pic_order_present_flag)) return false;
  info.pic_order_present_flag = (pic_order_present_flag != 0);

  info.valid = true;
  out = info;
  return true;
}

static SliceHeaderInfo parse_slice_header(const std::unordered_map<uint32_t, H264PpsInfo>& pps_map,
                                          const std::unordered_map<uint32_t, H264SpsInfo>& sps_map,
                                          int nal_type,
                                          const uint8_t* payload,
                                          size_t len) {
  SliceHeaderInfo info;
  if (!payload || len == 0) return info;

  std::vector<uint8_t> rbsp;
  nal_to_rbsp(payload, len, rbsp);
  if (rbsp.empty()) return info;

  BitReader br(rbsp);

  auto first_mb_in_slice = br.readUE();
  if (!first_mb_in_slice.has_value()) return info;
  info.first_mb_zero = (first_mb_in_slice.value() == 0);

  auto slice_type = br.readUE();
  if (!slice_type.has_value()) return info;
  (void)slice_type;

  auto pps_id = br.readUE();
  if (!pps_id.has_value()) return info;
  info.pps_id = pps_id.value();

  auto pps_it = pps_map.find(info.pps_id);
  if (pps_it == pps_map.end() || !pps_it->second.valid) return info;
  info.sps_id = pps_it->second.sps_id;
  auto sps_it = sps_map.find(info.sps_id);
  if (sps_it == sps_map.end() || !sps_it->second.valid) return info;
  const auto& sps = sps_it->second;
  const auto& pps = pps_it->second;

  if (sps.separate_colour_plane_flag) {
    if (!br.skipBits(2)) return info;
  }

  uint32_t frame_num = 0;
  if (!br.readBits(static_cast<int>(std::max<uint32_t>(4, sps.log2_max_frame_num)), frame_num)) return info;
  info.frame_num = frame_num;

  bool field_pic = false;
  if (!sps.frame_mbs_only_flag) {
    uint32_t field_flag = 0;
    if (!br.readBits(1, field_flag)) return info;
    field_pic = (field_flag != 0);
    if (field_pic) {
      uint32_t bottom_field_flag = 0;
      if (!br.readBits(1, bottom_field_flag)) return info;
    }
  }
  info.field_pic = field_pic;

  info.is_idr = (nal_type == 5);
  if (info.is_idr) {
    auto idr_pic_id = br.readUE();
    if (!idr_pic_id.has_value()) return info;
  }

  if (sps.pic_order_cnt_type == 0) {
    uint32_t poc_lsb = 0;
    if (!br.readBits(static_cast<int>(std::max<uint32_t>(4, sps.log2_max_pic_order_cnt_lsb)), poc_lsb)) return info;
    info.has_poc_lsb = true;
    info.pic_order_cnt_lsb = poc_lsb;
    if (pps.pic_order_present_flag && !field_pic) {
      auto delta_pic_order_cnt_bottom = br.readSE();
      if (!delta_pic_order_cnt_bottom.has_value()) return info;
    }
  } else if (sps.pic_order_cnt_type == 1) {
    if (!sps.delta_pic_order_always_zero_flag) {
      auto delta_pic_order_cnt0 = br.readSE();
      if (!delta_pic_order_cnt0.has_value()) return info;
    }
    if (pps.pic_order_present_flag && !field_pic) {
      auto delta_pic_order_cnt1 = br.readSE();
      if (!delta_pic_order_cnt1.has_value()) return info;
    }
  }

  info.valid = true;
  return info;
}

static inline int first_annexb_nal_type(const std::vector<uint8_t>& buf) {
  const size_t n = buf.size();
  for (size_t i = 0; i + 3 < n; ++i) {
    if (i + 4 <= n && buf[i]==0x00 && buf[i+1]==0x00 && buf[i+2]==0x00 && buf[i+3]==0x01) {
      size_t hdr = i + 4;
      if (hdr < n) return buf[hdr] & 0x1F;
      return -1;
    }
    if (buf[i]==0x00 && buf[i+1]==0x00 && buf[i+2]==0x01) {
      size_t hdr = i + 3;
      if (hdr < n) return buf[hdr] & 0x1F;
      return -1;
    }
  }
  return -1;
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

    pc->onStateChange([sess](rtc::PeerConnection::State st){
      if (st == rtc::PeerConnection::State::Connected) {
        sess->pcConnected.store(true);
        sess->lastActive = std::chrono::steady_clock::now();
        VA_LOG_C(::va::core::LogLevel::Info, "transport.webrtc") << "[WHEP] pc connected sid=" << sess->sid;
      } else if (st == rtc::PeerConnection::State::Closed || st == rtc::PeerConnection::State::Failed) {
        // 主动清理，避免悬挂会话在浏览器刷新/崩溃时长期存在，降低资源压力
        try { WhepSessionManager::instance().deleteSession(sess->sid); } catch (...) {}
      }
    });

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
  std::vector<std::pair<std::string, std::shared_ptr<Session>>> targets;
  {
    std::lock_guard<std::mutex> g(mu_);
    auto add_range = [&](const std::string& key) {
      auto range = indexByStream_.equal_range(key);
      for (auto it = range.first; it != range.second; ++it) {
        const auto& sid = it->second;
        auto sit = bySid_.find(sid);
        if (sit != bySid_.end() && sit->second && !sit->second->closed) {
          targets.emplace_back(sid, sit->second);
        }
      }
    };
    add_range(streamKey);
    auto pos = streamKey.find(':');
    if (pos != std::string::npos) add_range(streamKey.substr(0, pos));
    if (!targets.empty()) {
      std::unordered_set<std::string> seen;
      std::vector<std::pair<std::string, std::shared_ptr<Session>>> uniq;
      uniq.reserve(targets.size());
      for (auto& kv : targets) {
        if (seen.insert(kv.first).second) uniq.emplace_back(kv);
      }
      targets.swap(uniq);
    }
  }
  if (targets.empty()) return;

  std::vector<uint8_t> h264 = data;
  ensure_annexb(h264);
  if (h264.empty()) return;

  const auto frame_time = std::chrono::steady_clock::now();

  for (auto& kv : targets) {
    auto sess = kv.second;
    if (!sess || !sess->videoTrack) continue;
    if (!sess->pcConnected.load()) continue;
    bool closed = false;
    try { closed = sess->videoTrack->isClosed(); } catch (...) { closed = true; }
    if (closed) { sess->closed.store(true); continue; }
    bool open = false;
    try { open = sess->videoTrack->isOpen(); } catch (...) { open = false; }
    if (!open) continue;

    auto flush_pending = [&](bool force, std::chrono::steady_clock::time_point now_tp) {
      if (!sess->pending_has_vcl || sess->pending_au.empty()) return;
      if (!sess->started.load()) {
        if (!sess->pending_is_idr) {
          if (!force) return;
          sess->pending_au.clear();
          sess->pending_has_vcl = false;
          sess->pending_is_idr = false;
          sess->pending_has_sps = false;
          sess->pending_has_pps = false;
          sess->pending_started_at = {};
          sess->frame_state.have_prev = false;
          return;
        }
        if (sess->last_sps.empty() || sess->last_pps.empty()) {
          if (!force) return;
        }
      }

      if (sess->pending_is_idr) {
        sess->started.store(true);
      }
      if (!sess->started.load()) {
        return;
      }

      if (sess->pending_is_idr) {
        bool need_sps = !sess->pending_has_sps && !sess->last_sps.empty();
        bool need_pps = !sess->pending_has_pps && !sess->last_pps.empty();
        if (need_sps || need_pps) {
          std::vector<uint8_t> with;
          with.reserve((need_sps ? sess->last_sps.size() : 0) +
                       (need_pps ? sess->last_pps.size() : 0) +
                       sess->pending_au.size());
          if (need_sps) {
            with.insert(with.end(), sess->last_sps.begin(), sess->last_sps.end());
            sess->pending_has_sps = true;
          }
          if (need_pps) {
            with.insert(with.end(), sess->last_pps.begin(), sess->last_pps.end());
            sess->pending_has_pps = true;
          }
          with.insert(with.end(), sess->pending_au.begin(), sess->pending_au.end());
          sess->pending_au.swap(with);
        }
      }

      if (first_annexb_nal_type(sess->pending_au) != 9) {
        static const uint8_t aud[] = {0x00, 0x00, 0x00, 0x01, 0x09, 0xF0};
        std::vector<uint8_t> with_aud;
        with_aud.reserve(sizeof(aud) + sess->pending_au.size());
        with_aud.insert(with_aud.end(), aud, aud + sizeof(aud));
        with_aud.insert(with_aud.end(), sess->pending_au.begin(), sess->pending_au.end());
        sess->pending_au.swap(with_aud);
      }

      rtc::binary frame;
      frame.resize(sess->pending_au.size());
      std::memcpy(frame.data(), sess->pending_au.data(), sess->pending_au.size());

      const uint32_t next_ts = sess->ts90 + (90000u / 30u);
      rtc::FrameInfo finfo(next_ts);
      finfo.payloadType = sess->payloadType ? sess->payloadType : uint8_t(96);

      try {
        sess->videoTrack->sendFrame(std::move(frame), finfo);
      } catch (const std::exception& ex) {
        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000)
            << "[WHEP] sendFrame ex sid=" << kv.first << " err=" << ex.what();
        return;
      } catch (...) {
        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "transport.webrtc", 2000)
            << "[WHEP] sendFrame ex sid=" << kv.first;
        return;
      }

      sess->ts90 = next_ts;
      sess->dbg_frames += 1;
      sess->dbg_bytes += sess->pending_au.size();
      sess->lastActive = now_tp;
      sess->pending_au.clear();
      sess->pending_has_vcl = false;
      sess->pending_is_idr = false;
      sess->pending_has_sps = false;
      sess->pending_has_pps = false;
      sess->pending_started_at = {};
      sess->frame_state.have_prev = false;
    };

    size_t pos = 0;
    size_t sc_len = 0;
    while (true) {
      size_t start = find_start_code(h264, pos, sc_len);
      if (start == std::numeric_limits<size_t>::max()) break;
      size_t next_sc_len = 0;
      size_t next = find_start_code(h264, start + sc_len, next_sc_len);
      size_t end = (next == std::numeric_limits<size_t>::max()) ? h264.size() : next;
      size_t header = start + sc_len;
      if (header >= end) { pos = end; continue; }
      int nal_type = h264[header] & 0x1F;
      const uint8_t* nal_ptr = h264.data() + start;
      size_t nal_len = end - start;
      const uint8_t* payload = (header + 1 < end) ? (h264.data() + header + 1) : nullptr;
      size_t payload_len = (payload && end > header + 1) ? (end - (header + 1)) : 0;

      if (nal_type == 7 && payload && payload_len > 0) {
        H264SpsInfo sps_info;
        if (parse_sps(payload, payload_len, sps_info)) {
          sess->sps_map[sps_info.id] = sps_info;
        }
      } else if (nal_type == 8 && payload && payload_len > 0) {
        H264PpsInfo pps_info;
        if (parse_pps(payload, payload_len, pps_info)) {
          sess->pps_map[pps_info.id] = pps_info;
        }
      }

      if (is_vcl_nal(nal_type)) {
        SliceHeaderInfo shi = parse_slice_header(sess->pps_map, sess->sps_map, nal_type, payload, payload_len);
        if (sess->pending_has_vcl) {
          bool need_flush = false;
          if (shi.valid) {
            if (!sess->frame_state.have_prev) {
              need_flush = true;
            } else {
              if (shi.is_idr != sess->frame_state.is_idr) need_flush = true;
              if (shi.frame_num != sess->frame_state.frame_num) need_flush = true;
              if (shi.has_poc_lsb && sess->frame_state.has_poc_lsb &&
                  shi.pic_order_cnt_lsb != sess->frame_state.pic_order_cnt_lsb) need_flush = true;
              if (shi.has_poc_lsb != sess->frame_state.has_poc_lsb) need_flush = true;
              if (shi.field_pic != sess->frame_state.field_pic) need_flush = true;
            }
          } else if (shi.first_mb_zero) {
            need_flush = true;
          }
          if (need_flush) {
            flush_pending(false, frame_time);
          }
        }

        if (shi.valid) {
          sess->frame_state.have_prev = true;
          sess->frame_state.frame_num = shi.frame_num;
          sess->frame_state.is_idr = shi.is_idr;
          sess->frame_state.field_pic = shi.field_pic;
          sess->frame_state.has_poc_lsb = shi.has_poc_lsb;
          if (shi.has_poc_lsb) sess->frame_state.pic_order_cnt_lsb = shi.pic_order_cnt_lsb;
        } else if (sess->pending_has_vcl && shi.first_mb_zero) {
          flush_pending(false, frame_time);
        }

        if (!sess->pending_has_vcl) {
          if (!sess->pending_prefix.empty()) {
            sess->pending_au.insert(sess->pending_au.end(),
                                    sess->pending_prefix.begin(),
                                    sess->pending_prefix.end());
            if (sess->prefix_has_sps) sess->pending_has_sps = true;
            if (sess->prefix_has_pps) sess->pending_has_pps = true;
            sess->pending_prefix.clear();
            sess->prefix_has_sps = false;
            sess->prefix_has_pps = false;
          }
          if (nal_type == 5) {
            if (!sess->pending_has_sps && !sess->last_sps.empty()) {
              sess->pending_au.insert(sess->pending_au.end(),
                                      sess->last_sps.begin(), sess->last_sps.end());
              sess->pending_has_sps = true;
            }
            if (!sess->pending_has_pps && !sess->last_pps.empty()) {
              sess->pending_au.insert(sess->pending_au.end(),
                                      sess->last_pps.begin(), sess->last_pps.end());
              sess->pending_has_pps = true;
            }
          }
          sess->pending_has_vcl = true;
          sess->pending_is_idr = (nal_type == 5);
          sess->pending_started_at = frame_time;
        } else if (nal_type == 5) {
          sess->pending_is_idr = true;
        }

        sess->pending_au.insert(sess->pending_au.end(), nal_ptr, nal_ptr + nal_len);
      } else {
        if (nal_type == 7) {
          sess->last_sps.assign(nal_ptr, nal_ptr + nal_len);
        } else if (nal_type == 8) {
          sess->last_pps.assign(nal_ptr, nal_ptr + nal_len);
        }

        if (sess->pending_has_vcl) {
          sess->pending_au.insert(sess->pending_au.end(), nal_ptr, nal_ptr + nal_len);
          if (nal_type == 7) sess->pending_has_sps = true;
          else if (nal_type == 8) sess->pending_has_pps = true;
        } else {
          sess->pending_prefix.insert(sess->pending_prefix.end(), nal_ptr, nal_ptr + nal_len);
          if (nal_type == 7) sess->prefix_has_sps = true;
          else if (nal_type == 8) sess->prefix_has_pps = true;
        }
      }

      pos = end;
    }

    if (sess->pending_has_vcl) {
      auto now_guard = std::chrono::steady_clock::now();
      if (sess->pending_started_at != std::chrono::steady_clock::time_point{} &&
          now_guard - sess->pending_started_at > std::chrono::milliseconds(120)) {
        flush_pending(true, now_guard);
      }
    }
  }

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





