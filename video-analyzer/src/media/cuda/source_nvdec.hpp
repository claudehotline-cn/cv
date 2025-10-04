#pragma once

#include "media/source.hpp"
#include "core/buffer_pool.hpp"

#include <mutex>
#include <string>
#include <vector>
#include <chrono>

extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
}

struct SwsContext;

namespace va::media::cuda {

class NvdecRtspSource : public ISwitchableSource {
public:
    explicit NvdecRtspSource(std::string uri);

    bool start() override;
    void stop() override;
    bool read(core::Frame& frame) override;
    SourceStats stats() const override;
    bool switchUri(const std::string& uri) override;

private:
    bool open();
    void close();
    bool initCodec();
    bool fetchFrame(core::Frame& frame);
    bool transferFrame(AVFrame* src, core::Frame& dst);
    bool ensureFrameBuffer(int width, int height);
    bool prepareSurface(std::size_t total_bytes, va::core::MemoryHandle& handle);

    std::string uri_;
    mutable std::mutex mutex_;

    AVFormatContext* format_ctx_ {nullptr};
    AVCodecContext* codec_ctx_ {nullptr};
    const AVCodec* codec_ {nullptr};
    AVBufferRef* hw_device_ctx_ {nullptr};
    int video_stream_index_ {-1};

    AVPacket* packet_ {nullptr};
    AVFrame* hw_frame_ {nullptr};
    AVFrame* sw_frame_ {nullptr};
    SwsContext* sws_ctx_ {nullptr};

    std::vector<uint8_t> frame_buffer_;
    int last_width_ {0};
    int last_height_ {0};
    AVPixelFormat last_format_ {AV_PIX_FMT_NONE};

    bool running_ {false};
    uint64_t frame_counter_ {0};
    double avg_latency_ms_ {0.0};
    std::chrono::steady_clock::time_point started_at_;
    std::chrono::steady_clock::time_point last_frame_time_;

    std::shared_ptr<va::core::GpuBufferPool> surface_pool_;
    std::size_t surface_pool_bytes_ {0};
};

} // namespace va::media::cuda
