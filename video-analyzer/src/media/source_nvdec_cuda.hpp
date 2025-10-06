#pragma once

#include "media/source_switchable_rtsp.hpp"

#ifdef USE_FFMPEG
extern "C" {
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libavutil/hwcontext.h>
#include <libavutil/imgutils.h>
#include <libswscale/swscale.h>
}
#endif

#include <mutex>

// NVDEC-based RTSP/File source (safe fallback to CPU if unavailable)
namespace va::media {

class NvdecRtspSource : public ISwitchableSource {
public:
    explicit NvdecRtspSource(std::string uri);
    ~NvdecRtspSource() override;

    bool start() override;
    void stop() override;
    bool read(va::core::Frame& frame) override;
    SourceStats stats() const override;
    bool switchUri(const std::string& uri) override;

private:
    bool openImpl();
    void closeImpl();
    bool readImpl(va::core::Frame& frame);

private:
    std::string uri_;
    mutable std::mutex mutex_;
    bool running_ {false};
    uint64_t frame_counter_ {0};
    double avg_latency_ms_ {0.0};
    std::chrono::steady_clock::time_point started_at_;
    std::chrono::steady_clock::time_point last_frame_time_;

    // CPU fallback path
    SwitchableRtspSource cpu_fallback_;

#ifdef USE_FFMPEG
    AVFormatContext* fmt_ctx_ {nullptr};
    AVCodecContext* dec_ctx_ {nullptr};
    AVBufferRef* hw_device_ctx_ {nullptr};
    SwsContext* sws_ {nullptr};
    int video_stream_ {-1};
    AVPixelFormat sw_pix_fmt_ {AV_PIX_FMT_BGR24};
    int width_ {0};
    int height_ {0};
    // Wait for first IDR/KEY frame to reduce NVDEC startup decode failures
    bool awaiting_idr_ {true};
    bool idr_log_printed_ {false};
#endif
public:
#ifdef USE_FFMPEG
    AVBufferRef* hwDeviceCtx() const { return hw_device_ctx_ ? av_buffer_ref(hw_device_ctx_) : nullptr; }
#endif
};

} // namespace va::media

// Factory symbol used by composition_root to avoid direct header coupling
namespace va::media {
    std::shared_ptr<ISwitchableSource> makeNvdecSource(const std::string& uri);
}
