#pragma once

#include "media/source.hpp"

#include <chrono>
#include <mutex>
#include <string>

extern "C" {
#ifdef USE_FFMPEG
#include <libavcodec/avcodec.h>
#include <libavformat/avformat.h>
#include <libswscale/swscale.h>
#endif
}

namespace va::media {

class FfmpegRtspSource : public ISwitchableSource {
public:
    explicit FfmpegRtspSource(std::string uri);
    ~FfmpegRtspSource() override;

    bool start() override;
    void stop() override;
    bool read(core::Frame& frame) override;
    SourceStats stats() const override;
    bool switchUri(const std::string& uri) override;

private:
    bool openImpl();
    void closeImpl();
    bool readImpl(core::Frame& frame);

    std::string uri_;
    mutable std::mutex mutex_;
    bool running_ {false};

    // Stats
    uint64_t frame_counter_ {0};
    std::chrono::steady_clock::time_point started_at_ {};
    std::chrono::steady_clock::time_point last_frame_time_ {};
    double avg_latency_ms_ {0.0};

    // Reopen/backoff
    int fail_count_ {0};
    int backoff_ms_ {0};
    std::chrono::steady_clock::time_point next_reopen_ {};
    bool is_rtsp_ {false};

#ifdef USE_FFMPEG
    AVFormatContext* fmt_ {nullptr};
    AVCodecContext* dec_ {nullptr};
    int video_stream_ {-1};
    SwsContext* sws_ {nullptr};
#endif
};

} // namespace va::media
