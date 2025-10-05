#include "media/encoder_h264_nvenc.hpp"

namespace va::media {

bool NvencH264Encoder::open(const Settings& settings) {
    Settings s = settings;
    // Prefer FFmpeg NVENC encoder if not explicitly set
    if (s.codec.empty() || s.codec == "h264") {
        s.codec = "h264_nvenc";
    }
    return inner_.open(s);
}

bool NvencH264Encoder::encode(const va::core::Frame& frame, Packet& out_packet) {
    return inner_.encode(frame, out_packet);
}

void NvencH264Encoder::close() {
    inner_.close();
}

std::shared_ptr<IEncoder> makeNvencEncoder(const va::core::EncoderConfig& cfg) {
    auto enc = std::make_shared<NvencH264Encoder>();
    IEncoder::Settings s;
    s.width = cfg.width;
    s.height = cfg.height;
    s.fps = cfg.fps;
    s.bitrate_kbps = cfg.bitrate_kbps;
    s.gop = cfg.gop;
    s.bframes = cfg.bframes;
    s.zero_latency = cfg.zero_latency;
    s.preset = cfg.preset;
    s.tune = cfg.tune;
    s.profile = cfg.profile;
    s.codec = cfg.codec.empty() ? std::string{"h264_nvenc"} : cfg.codec;
    if (!enc->open(s)) {
        return {};
    }
    return enc;
}

} // namespace va::media

