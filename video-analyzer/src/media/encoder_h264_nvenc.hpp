#pragma once

#include "media/encoder.hpp"
#include "media/encoder_h264_ffmpeg.hpp"
#include "core/factories.hpp"

// Lightweight NVENC wrapper using FFmpeg's h264_nvenc encoder.
// Keeps the same IEncoder interface and delegates most logic to the
// existing FfmpegH264Encoder, only preferring the NVENC codec name.

namespace va::media {

class NvencH264Encoder : public IEncoder {
public:
    NvencH264Encoder() = default;
    ~NvencH264Encoder() override = default;

    bool open(const Settings& settings) override;
    bool encode(const va::core::Frame& frame, Packet& out_packet) override;
    void close() override;
    void requestKeyframe() override { inner_.requestKeyframe(); }

private:
    FfmpegH264Encoder inner_;
};

std::shared_ptr<IEncoder> makeNvencEncoder(const va::core::EncoderConfig& cfg);

} // namespace va::media
