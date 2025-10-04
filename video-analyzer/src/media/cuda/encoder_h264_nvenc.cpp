#include "media/cuda/encoder_h264_nvenc.hpp"

#include "core/logger.hpp"

namespace va::media::cuda {

NvencH264Encoder::NvencH264Encoder() = default;
NvencH264Encoder::~NvencH264Encoder() = default;

bool NvencH264Encoder::open(const Settings& settings) {
    settings_ = settings;
    Settings nvenc_settings = settings;
    if (nvenc_settings.codec.empty() || nvenc_settings.codec == "h264") {
        nvenc_settings.codec = "h264_nvenc";
    }
    if (ffmpeg_.open(nvenc_settings)) {
        opened_ = true;
        using_cpu_fallback_ = false;
        VA_LOG_INFO() << "[NVENC] Encoder opened (" << nvenc_settings.width << "x" << nvenc_settings.height
                      << " @ " << nvenc_settings.fps << " fps, bitrate " << nvenc_settings.bitrate_kbps
                      << " kbps)";
        return true;
    }

    VA_LOG_WARN() << "[NVENC] Failed to open h264_nvenc encoder, falling back to CPU implementation.";
    if (!ffmpeg_.open(settings)) {
        opened_ = false;
        return false;
    }
    opened_ = true;
    using_cpu_fallback_ = true;
    VA_LOG_INFO() << "[NVENC] CPU fallback encoder opened (" << settings.width << "x" << settings.height
                  << " @ " << settings.fps << " fps)";
    return true;
}

bool NvencH264Encoder::encode(const core::Frame& frame, Packet& out_packet) {
    if (!opened_) {
        return false;
    }
    return ffmpeg_.encode(frame, out_packet);
}

bool NvencH264Encoder::encode(const core::FrameSurface& surface, Packet& out_packet) {
    if (!opened_) {
        return false;
    }
    core::Frame frame;
    if (!core::surfaceToFrame(surface, frame)) {
        return false;
    }
    return ffmpeg_.encode(frame, out_packet);
}

void NvencH264Encoder::close() {
    if (opened_) {
        ffmpeg_.close();
        opened_ = false;
        using_cpu_fallback_ = false;
        VA_LOG_INFO() << "[NVENC] encoder closed";
    }
}

} // namespace va::media::cuda
