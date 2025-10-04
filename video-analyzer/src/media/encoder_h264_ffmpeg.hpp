#pragma once

#include "media/encoder.hpp"

#include <string>

#ifdef USE_FFMPEG
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavutil/opt.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}
#endif

#include <opencv2/imgcodecs.hpp>

namespace va::media {

class FfmpegH264Encoder : public IEncoder {
public:
    FfmpegH264Encoder();
    ~FfmpegH264Encoder() override;

    bool open(const Settings& settings) override;
    bool encode(const core::Frame& frame, Packet& out_packet) override;
    bool encode(const core::FrameSurface& surface, Packet& out_packet) override;
    void close() override;

private:
    bool opened_ {false};
    int width_ {0};
    int height_ {0};
    int fps_ {0};
    int64_t pts_ {0};
    bool use_jpeg_ {false};
    int jpeg_quality_ {80};
#ifdef USE_FFMPEG
    AVCodecContext* codec_ctx_ {nullptr};
    AVFrame* frame_ {nullptr};
    AVPacket* packet_ {nullptr};
    SwsContext* sws_ctx_ {nullptr};
#endif
};

} // namespace va::media
