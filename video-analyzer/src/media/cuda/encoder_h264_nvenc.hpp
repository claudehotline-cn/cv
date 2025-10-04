#pragma once

#include "media/encoder.hpp"
#include "media/encoder_h264_ffmpeg.hpp"

#include <memory>

namespace va::media::cuda {

class NvencH264Encoder : public IEncoder {
public:
    NvencH264Encoder();
    ~NvencH264Encoder() override;

    bool open(const Settings& settings) override;
    bool encode(const core::Frame& frame, Packet& out_packet) override;
    bool encode(const core::FrameSurface& surface, Packet& out_packet) override;
    void close() override;

private:
    va::media::FfmpegH264Encoder ffmpeg_;
    Settings settings_;
    bool opened_ {false};
    bool using_cpu_fallback_ {false};
};

} // namespace va::media::cuda
