#pragma once

#include "media/source.hpp"
#include "core/buffer_pool.hpp"

#include <mutex>
#include <string>
#include <chrono>

#include <opencv2/videoio.hpp>

namespace va::media {

class SwitchableRtspSource : public ISwitchableSource {
public:
    explicit SwitchableRtspSource(std::string uri);

    bool start() override;
    void stop() override;
    bool read(core::Frame& frame) override;
    SourceStats stats() const override;
    bool switchUri(const std::string& uri) override;

private:
    bool openCapture();
    void closeCapture();

    std::string uri_;
    mutable std::mutex mutex_;
    cv::VideoCapture capture_;
    bool running_ {false};

    uint64_t frame_counter_ {0};
    std::chrono::steady_clock::time_point started_at_;
    std::chrono::steady_clock::time_point last_frame_time_;
    double avg_latency_ms_ {0.0};

    std::size_t pool_block_bytes_ {0};
    std::shared_ptr<va::core::HostBufferPool> host_pool_;
};

} // namespace va::media
