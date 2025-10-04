#include "media/source_switchable_rtsp.hpp"

#include <cstring>
#include <opencv2/imgproc.hpp>

#include "core/logger.hpp"
#include "core/utils.hpp"

namespace va::media {

SwitchableRtspSource::SwitchableRtspSource(std::string uri)
    : uri_(std::move(uri)) {}

bool SwitchableRtspSource::start() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        return true;
    }
    if (!openCapture()) {
        VA_LOG_WARN() << "[RTSP] initial capture open failed for URI " << uri_ << ", will retry lazily";
    }
    running_ = true;
    frame_counter_ = 0;
    avg_latency_ms_ = 0.0;
    started_at_ = std::chrono::steady_clock::now();
    last_frame_time_ = started_at_;
    return true;
}

void SwitchableRtspSource::stop() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_) {
        return;
    }
    running_ = false;
    closeCapture();
}

bool SwitchableRtspSource::read(core::Frame& frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_) {
        return false;
    }
    if (!capture_.isOpened()) {
        if (!openCapture()) {
            VA_LOG_WARN() << "[RTSP] reopen failed for URI " << uri_;
            return false;
        }
    }

    cv::Mat mat;
    if (!capture_.read(mat) || mat.empty()) {
        VA_LOG_WARN() << "[RTSP] failed to read frame for URI " << uri_;
        return false;
    }

    frame_counter_++;
    last_frame_time_ = std::chrono::steady_clock::now();

    avg_latency_ms_ = 0.0;

    frame.width = mat.cols;
    frame.height = mat.rows;
    frame.pts_ms = core::ms_now();
    if (!mat.isContinuous()) {
        mat = mat.clone();
    }
    const std::size_t required_bytes = mat.total() * mat.elemSize();
    const int pitch = static_cast<int>(mat.step);

    if (!host_pool_ || pool_block_bytes_ < required_bytes) {
        host_pool_ = std::make_shared<va::core::HostBufferPool>(required_bytes, 8, true);
        pool_block_bytes_ = required_bytes;
    }

    auto handle = host_pool_->acquire();
    if (!handle.host_ptr || handle.bytes < required_bytes) {
        host_pool_->release(std::move(handle));
        return false;
    }

    std::memcpy(handle.host_ptr, mat.data, required_bytes);
    handle.bytes = required_bytes;
    handle.pitch = pitch;
    handle.width = frame.width;
    handle.height = frame.height;
    handle.location = va::core::MemoryLocation::Host;
    handle.format = va::core::PixelFormat::BGR24;
    handle.device_ptr = nullptr;
    handle.device_owner.reset();

    frame.bgr.clear();
    frame.surface.handle = std::move(handle);
    frame.surface.width = frame.width;
    frame.surface.height = frame.height;
    frame.surface.pts_ms = frame.pts_ms;
    frame.has_surface = true;
    frame.surface_recycle = [pool = std::weak_ptr<va::core::HostBufferPool>(host_pool_)](va::core::MemoryHandle&& handle) mutable {
        if (auto locked = pool.lock()) {
            locked->release(std::move(handle));
        }
    };

    return true;
}

SourceStats SwitchableRtspSource::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    SourceStats stats;
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_at_).count();
    if (elapsed > 0.0) {
        stats.fps = static_cast<double>(frame_counter_) * 1000.0 / elapsed;
    }
    stats.avg_latency_ms = avg_latency_ms_;
    stats.last_frame_id = frame_counter_;
    return stats;
}

bool SwitchableRtspSource::switchUri(const std::string& uri) {
    std::lock_guard<std::mutex> lock(mutex_);
    uri_ = uri;
    closeCapture();
    if (running_) {
        return openCapture();
    }
    return true;
}

bool SwitchableRtspSource::openCapture() {
    capture_.release();
    cv::VideoCapture cap(uri_, cv::CAP_FFMPEG);
    if (!cap.isOpened()) {
        VA_LOG_ERROR() << "[RTSP] cv::VideoCapture open failed for URI " << uri_;
        return false;
    }
    capture_ = std::move(cap);
    return true;
}

void SwitchableRtspSource::closeCapture() {
    if (capture_.isOpened()) {
        capture_.release();
    }
}

} // namespace va::media
