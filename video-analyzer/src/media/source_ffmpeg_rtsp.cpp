#include "media/source_ffmpeg_rtsp.hpp"
#include "core/logger.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"

namespace va::media {

FfmpegRtspSource::FfmpegRtspSource(std::string uri)
    : uri_(std::move(uri)) {}

FfmpegRtspSource::~FfmpegRtspSource() {
    stop();
}

bool FfmpegRtspSource::start() {
    std::lock_guard<std::mutex> lk(mutex_);
    if (running_) return true;
    frame_counter_ = 0;
    avg_latency_ms_ = 0.0;
    started_at_ = std::chrono::steady_clock::now();
    last_frame_time_ = started_at_;
#ifdef USE_FFMPEG
    is_rtsp_ = (uri_.rfind("rtsp://", 0) == 0 || uri_.rfind("rtsps://", 0) == 0);
    VA_LOG_C(::va::core::LogLevel::Info, "source.ffmpeg") << "source start uri=" << uri_ << ", is_rtsp=" << (is_rtsp_ ? "true" : "false");
    if (!openImpl()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "source.ffmpeg") << "initial open failed for uri " << uri_ << ", will retry lazily";
    }
#else
    VA_LOG_C(::va::core::LogLevel::Warn, "source.ffmpeg") << "FFmpeg is not enabled in this build; source will not produce frames.";
#endif
    running_ = true;
    return true;
}

void FfmpegRtspSource::stop() {
    std::lock_guard<std::mutex> lk(mutex_);
    if (!running_) return;
    running_ = false;
    closeImpl();
}

bool FfmpegRtspSource::read(core::Frame& frame) {
    std::lock_guard<std::mutex> lk(mutex_);
    if (!running_) return false;

#ifdef USE_FFMPEG
    if (!fmt_ || !dec_) {
        const auto now = std::chrono::steady_clock::now();
        if (is_rtsp_ && (next_reopen_.time_since_epoch().count() == 0 || now >= next_reopen_)) {
            const bool scheduled_reopen = (next_reopen_.time_since_epoch().count() != 0) && now >= next_reopen_;
            if (!openImpl()) {
                backoff_ms_ = backoff_ms_ == 0 ? 200 : std::min(backoff_ms_ * 2, 5000);
                next_reopen_ = now + std::chrono::milliseconds(backoff_ms_);
                VA_LOG_C(::va::core::LogLevel::Warn, "source.ffmpeg") << "reopen failed for uri " << uri_ << ", backoff=" << backoff_ms_ << "ms";
                return false;
            }
            backoff_ms_ = 0;
            next_reopen_ = {};
            fail_count_ = 0;
            if (scheduled_reopen) {
                // Count successful reconnection events per source_id
                va::core::SourceReconnects::incrementByUri(uri_, 1);
            }
        } else if (is_rtsp_) {
            return false;
        } else {
            // File input: attempt immediate open once
            if (!openImpl()) {
                return false;
            }
        }
    }

    if (!readImpl(frame)) {
        if (is_rtsp_) {
            ++fail_count_;
            if (fail_count_ >= 5) {
                closeImpl();
                const auto now = std::chrono::steady_clock::now();
                backoff_ms_ = backoff_ms_ == 0 ? 200 : std::min(backoff_ms_ * 2, 5000);
                next_reopen_ = now + std::chrono::milliseconds(backoff_ms_);
                VA_LOG_C(::va::core::LogLevel::Warn, "source.ffmpeg") << "too many read failures, scheduling reopen in " << backoff_ms_ << "ms for uri " << uri_;
                fail_count_ = 0;
            }
        }
        return false;
    }
    fail_count_ = 0;
    frame_counter_++;
    last_frame_time_ = std::chrono::steady_clock::now();
    return true;
#else
    (void)frame; return false;
#endif
}

SourceStats FfmpegRtspSource::stats() const {
    std::lock_guard<std::mutex> lk(mutex_);
    SourceStats s;
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_at_).count();
    if (elapsed > 0.0) s.fps = static_cast<double>(frame_counter_) * 1000.0 / elapsed;
    s.avg_latency_ms = avg_latency_ms_;
    s.last_frame_id = frame_counter_;
    return s;
}

bool FfmpegRtspSource::switchUri(const std::string& uri) {
    std::lock_guard<std::mutex> lk(mutex_);
    uri_ = uri;
    closeImpl();
    return true;
}

bool FfmpegRtspSource::openImpl() {
#ifndef USE_FFMPEG
    return false;
#else
    closeImpl();
    AVDictionary* opts = nullptr;
    if (is_rtsp_) {
        // Connection/transport
        av_dict_set(&opts, "rtsp_transport", "tcp", 0);
        av_dict_set(&opts, "rtsp_flags", "prefer_tcp", 0);
        // Timeouts (microseconds)
        av_dict_set(&opts, "stimeout", "5000000", 0);    // socket open timeout
        av_dict_set(&opts, "rw_timeout", "5000000", 0);  // IO read/write timeout
        // Low-latency tuning
        av_dict_set(&opts, "flags", "low_delay", 0);
        av_dict_set(&opts, "fflags", "nobuffer", 0);
        av_dict_set(&opts, "max_delay", "0", 0);
        av_dict_set(&opts, "reorder_queue_size", "0", 0);
        // Buffers & UA (best-effort)
        av_dict_set(&opts, "buffer_size", "1048576", 0);
        av_dict_set(&opts, "user_agent", "VideoAnalyzer/1.0", 0);
    }

    VA_LOG_C(::va::core::LogLevel::Info, "source.ffmpeg") << "avformat_open_input uri=" << uri_;
    int open_ret = avformat_open_input(&fmt_, uri_.c_str(), nullptr, &opts);
    if (open_ret < 0) {
        av_dict_free(&opts);
        fmt_ = nullptr;
        char err[256]; err[0]='\0';
        av_strerror(open_ret, err, sizeof(err));
        VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "avformat_open_input failed ret=" << open_ret << " (" << err << ")";
        return false;
    }
    av_dict_free(&opts);
    int sinfo = avformat_find_stream_info(fmt_, nullptr);
    if (sinfo < 0) {
        char err[256]; err[0]='\0';
        av_strerror(sinfo, err, sizeof(err));
        VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "avformat_find_stream_info failed ret=" << sinfo << " (" << err << ")";
        closeImpl();
        return false;
    }
    video_stream_ = av_find_best_stream(fmt_, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (video_stream_ < 0) {
        VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "no video stream";
        closeImpl();
        return false;
    }
    AVStream* st = fmt_->streams[video_stream_];
    const AVCodec* dec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!dec) { VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "no decoder"; closeImpl(); return false; }
    dec_ = avcodec_alloc_context3(dec);
    if (!dec_) { VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "alloc context failed"; closeImpl(); return false; }
    if (avcodec_parameters_to_context(dec_, st->codecpar) < 0) { VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "copy params failed"; closeImpl(); return false; }
    {
        int aopen = avcodec_open2(dec_, dec, nullptr);
        if (aopen < 0) {
            char err[256]; err[0]='\0';
            av_strerror(aopen, err, sizeof(err));
            VA_LOG_C(::va::core::LogLevel::Error, "source.ffmpeg") << "avcodec_open2 failed ret=" << aopen << " (" << err << ")";
            closeImpl(); return false;
        }
    }
    VA_LOG_C(::va::core::LogLevel::Info, "source.ffmpeg") << "open OK: " << dec_->width << "x" << dec_->height;
    return true;
#endif
}

void FfmpegRtspSource::closeImpl() {
#ifdef USE_FFMPEG
    if (sws_) { sws_freeContext(sws_); sws_ = nullptr; }
    if (dec_) { avcodec_free_context(&dec_); dec_ = nullptr; }
    if (fmt_) { avformat_close_input(&fmt_); fmt_ = nullptr; }
#endif
}

bool FfmpegRtspSource::readImpl(core::Frame& frame) {
#ifndef USE_FFMPEG
    (void)frame; return false;
#else
    if (!fmt_ || !dec_) return false;
    AVPacket pkt; av_init_packet(&pkt);
    AVFrame* f = av_frame_alloc();
    bool ok = false;
    int read_ret = 0;
    while ((read_ret = av_read_frame(fmt_, &pkt)) >= 0) {
        if (pkt.stream_index != video_stream_) { av_packet_unref(&pkt); continue; }
        if (avcodec_send_packet(dec_, &pkt) < 0) { av_packet_unref(&pkt); break; }
        av_packet_unref(&pkt);
        while (true) {
            int ret = avcodec_receive_frame(dec_, f);
            if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
            if (ret < 0) { break; }

            if (!sws_) {
                sws_ = sws_getContext(f->width, f->height, static_cast<AVPixelFormat>(f->format),
                                       f->width, f->height, AV_PIX_FMT_BGR24,
                                       SWS_BILINEAR, nullptr, nullptr, nullptr);
                if (!sws_) { continue; }
            }
            frame.width = f->width; frame.height = f->height; frame.pts_ms = va::core::ms_now();
            frame.bgr.resize(static_cast<size_t>(frame.width) * frame.height * 3u);
            uint8_t* dst_data[4] = { frame.bgr.data(), nullptr, nullptr, nullptr };
            int dst_linesize[4] = { frame.width * 3, 0, 0, 0 };
            sws_scale(sws_, f->data, f->linesize, 0, f->height, dst_data, dst_linesize);
            ok = true;
            VA_LOG_EVERY_N(::va::core::LogLevel::Debug, "source.ffmpeg", 120) << "read frame " << frame.width << "x" << frame.height;
            break;
        }
        if (ok) break;
    }
    if (read_ret < 0 && read_ret != AVERROR_EOF) {
        char err[128]; err[0]='\0';
        av_strerror(read_ret, err, sizeof(err));
        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "source.ffmpeg", 2000) << "av_read_frame ret=" << read_ret << " (" << err << ")";
        // Attribute decode error to current source via URI mapping
        va::core::DropMetrics::incrementByUri(uri_, va::core::DropMetrics::Reason::DecodeError, 1);
    }
    if (!is_rtsp_ && read_ret == AVERROR_EOF) {
        // Loop file inputs: seek back to start and flush decoder
        avcodec_flush_buffers(dec_);
        if (av_seek_frame(fmt_, -1, 0, AVSEEK_FLAG_BACKWARD) >= 0) {
            ok = false; // not yet produced frame in this call
        }
    }
    av_frame_free(&f);
    return ok;
#endif
}

} // namespace va::media
