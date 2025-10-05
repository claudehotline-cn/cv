#include "media/source_switchable_rtsp.hpp"

#include <opencv2/imgproc.hpp>

#include "core/logger.hpp"

namespace va::media {

SwitchableRtspSource::SwitchableRtspSource(std::string uri)
    : uri_(std::move(uri)) {}

bool SwitchableRtspSource::start() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        return true;
    }
    VA_LOG_INFO() << "[RTSP] source start uri=" << uri_;
    if (!openCapture()) {
        VA_LOG_WARN() << "[RTSP] initial capture open failed for URI " << uri_ << ", will retry lazily";
    }
    running_ = true;
    frame_counter_ = 0;
    avg_latency_ms_ = 0.0;
    started_at_ = std::chrono::steady_clock::now();
    last_frame_time_ = started_at_;
    consecutive_fail_read_ = 0;
    backoff_ms_ = 0;
    next_reopen_time_ = {};
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
        const auto now = std::chrono::steady_clock::now();
        if (next_reopen_time_.time_since_epoch().count() == 0 || now >= next_reopen_time_) {
            if (!openCapture()) {
                // incremental backoff: 200ms -> 5s
                backoff_ms_ = backoff_ms_ == 0 ? 200 : std::min(backoff_ms_ * 2, 5000);
                next_reopen_time_ = now + std::chrono::milliseconds(backoff_ms_);
                VA_LOG_WARN() << "[RTSP] reopen failed for URI " << uri_ << ", backoff=" << backoff_ms_ << "ms";
                return false;
            }
            // success resets backoff
            backoff_ms_ = 0;
            next_reopen_time_ = {};
            consecutive_fail_read_ = 0;
        } else {
            // not yet time to reopen; throttle attempts
            return false;
        }
    }

    cv::Mat mat;
    if (!capture_.read(mat) || mat.empty()) {
        consecutive_fail_read_++;
        VA_LOG_WARN() << "[RTSP] failed to read frame for URI " << uri_ << ", fail_count=" << consecutive_fail_read_;
        if (consecutive_fail_read_ >= 5) {
            // Force reopen with backoff
            capture_.release();
            const auto now = std::chrono::steady_clock::now();
            backoff_ms_ = backoff_ms_ == 0 ? 200 : std::min(backoff_ms_ * 2, 5000);
            next_reopen_time_ = now + std::chrono::milliseconds(backoff_ms_);
            VA_LOG_WARN() << "[RTSP] too many failures, scheduling reopen in " << backoff_ms_ << "ms for URI " << uri_;
            consecutive_fail_read_ = 0;
        }
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
    frame.bgr.assign(mat.datastart, mat.dataend);
    consecutive_fail_read_ = 0;

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
    std::string open_uri = uri_;
    // Normalize Windows path to forward slashes; if file exists, allow implicit file path
    try {
        // avoid C++17 fs issues on some toolchains: use simple heuristic
        if (open_uri.size() > 2 && ((open_uri[1] == ':' && (open_uri[2] == '\\' || open_uri[2] == '/')))) {
            for (auto& ch : open_uri) { if (ch == '\\') ch = '/'; }
        }
    } catch (...) {}
    // Prefer TCP and low-latency options via FFmpeg URL parameters
    if (open_uri.rfind("rtsp://", 0) == 0) {
        const bool has_query = (open_uri.find('?') != std::string::npos);
        open_uri.push_back(has_query ? '&' : '?');
        open_uri += "rtsp_transport=tcp&stimeout=5000000&fflags=nobuffer&flags=low_delay&reorder_queue_size=0";
    }
    VA_LOG_INFO() << "[RTSP] opening via OpenCV/FFmpeg uri=" << open_uri;
    cv::VideoCapture cap(open_uri, cv::CAP_FFMPEG);
    if (!cap.isOpened()) {
        VA_LOG_ERROR() << "[RTSP] cv::VideoCapture open failed for URI " << uri_;
        return false;
    }
    capture_ = std::move(cap);
    // Reduce internal buffer if supported (best-effort)
    try { capture_.set(cv::CAP_PROP_BUFFERSIZE, 1); } catch (...) {}
    VA_LOG_INFO() << "[RTSP] cv::VideoCapture opened OK uri=" << uri_;
    return true;
}

void SwitchableRtspSource::closeCapture() {
    if (capture_.isOpened()) {
        capture_.release();
    }
}

} // namespace va::media

