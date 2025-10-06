#include "media/source_nvdec_cuda.hpp"
#include "core/logger.hpp"

namespace va::media {

namespace {
#ifdef USE_FFMPEG
static enum AVPixelFormat get_hw_format(AVCodecContext* ctx, const enum AVPixelFormat* pix_fmts)
{
    for (const enum AVPixelFormat* p = pix_fmts; *p != AV_PIX_FMT_NONE; p++) {
        if (*p == AV_PIX_FMT_CUDA) {
            return *p;
        }
    }
    return ctx->sw_pix_fmt; // fallback
}
#endif
}

NvdecRtspSource::NvdecRtspSource(std::string uri)
    : uri_(std::move(uri)), cpu_fallback_(uri_) {}

NvdecRtspSource::~NvdecRtspSource() {
    stop();
}

bool NvdecRtspSource::start() {
    std::lock_guard<std::mutex> lk(mutex_);
    if (running_) return true;
    frame_counter_ = 0;
    avg_latency_ms_ = 0.0;
    started_at_ = std::chrono::steady_clock::now();
    last_frame_time_ = started_at_;
    bool ok = openImpl();
    if (!ok) {
        VA_LOG_WARN() << "[NVDEC] falling back to CPU for URI " << uri_;
        ok = cpu_fallback_.start();
    }
    running_ = ok;
    return ok;
}

void NvdecRtspSource::stop() {
    std::lock_guard<std::mutex> lk(mutex_);
    if (!running_) return;
    running_ = false;
    closeImpl();
    cpu_fallback_.stop();
}

bool NvdecRtspSource::read(va::core::Frame& frame) {
    std::lock_guard<std::mutex> lk(mutex_);
    if (!running_) return false;
    if (fmt_ctx_ && dec_ctx_) {
        if (readImpl(frame)) {
            frame_counter_++;
            last_frame_time_ = std::chrono::steady_clock::now();
            return true;
        }
        // If NVDEC path fails transiently, try CPU fallback
    }
    return cpu_fallback_.read(frame);
}

SourceStats NvdecRtspSource::stats() const {
    std::lock_guard<std::mutex> lk(mutex_);
    SourceStats s;
    const auto now = std::chrono::steady_clock::now();
    const double elapsed = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_at_).count();
    if (elapsed > 0.0) s.fps = static_cast<double>(frame_counter_) * 1000.0 / elapsed;
    s.avg_latency_ms = avg_latency_ms_;
    s.last_frame_id = frame_counter_;
    return s;
}

bool NvdecRtspSource::switchUri(const std::string& uri) {
    std::lock_guard<std::mutex> lk(mutex_);
    uri_ = uri;
    closeImpl();
    cpu_fallback_.switchUri(uri);
    return true;
}

bool NvdecRtspSource::openImpl() {
#ifndef USE_FFMPEG
    return false;
#else
    closeImpl();
    if (avformat_open_input(&fmt_ctx_, uri_.c_str(), nullptr, nullptr) < 0) {
        fmt_ctx_ = nullptr;
        return false;
    }
    if (avformat_find_stream_info(fmt_ctx_, nullptr) < 0) {
        closeImpl();
        return false;
    }
    video_stream_ = av_find_best_stream(fmt_ctx_, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (video_stream_ < 0) {
        closeImpl();
        return false;
    }
    AVStream* st = fmt_ctx_->streams[video_stream_];
    const AVCodec* dec = avcodec_find_decoder(st->codecpar->codec_id);
    if (!dec) { closeImpl(); return false; }
    dec_ctx_ = avcodec_alloc_context3(dec);
    if (!dec_ctx_) { closeImpl(); return false; }
    if (avcodec_parameters_to_context(dec_ctx_, st->codecpar) < 0) { closeImpl(); return false; }

    // Try create CUDA hwdevice
    if (av_hwdevice_ctx_create(&hw_device_ctx_, AV_HWDEVICE_TYPE_CUDA, nullptr, nullptr, 0) == 0) {
        dec_ctx_->hw_device_ctx = av_buffer_ref(hw_device_ctx_);
        dec_ctx_->get_format = get_hw_format;
    }

    if (avcodec_open2(dec_ctx_, dec, nullptr) < 0) { closeImpl(); return false; }
    width_ = dec_ctx_->width;
    height_ = dec_ctx_->height;
    return true;
#endif
}

void NvdecRtspSource::closeImpl() {
#ifdef USE_FFMPEG
    if (sws_) { sws_freeContext(sws_); sws_ = nullptr; }
    if (dec_ctx_) { avcodec_free_context(&dec_ctx_); dec_ctx_ = nullptr; }
    if (fmt_ctx_) { avformat_close_input(&fmt_ctx_); fmt_ctx_ = nullptr; }
    if (hw_device_ctx_) { av_buffer_unref(&hw_device_ctx_); hw_device_ctx_ = nullptr; }
#endif
}

bool NvdecRtspSource::readImpl(va::core::Frame& frame) {
#ifndef USE_FFMPEG
    (void)frame; return false;
#else
    AVPacket pkt; av_init_packet(&pkt);
    AVFrame* f = av_frame_alloc();
    AVFrame* sw = av_frame_alloc();
    bool ok = false;
    while (av_read_frame(fmt_ctx_, &pkt) >= 0) {
        if (pkt.stream_index != video_stream_) { av_packet_unref(&pkt); continue; }
        if (avcodec_send_packet(dec_ctx_, &pkt) < 0) { av_packet_unref(&pkt); break; }
        av_packet_unref(&pkt);
        while (true) {
            int ret = avcodec_receive_frame(dec_ctx_, f);
            if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) break;
            if (ret < 0) { break; }

            AVFrame* src = f;
            if (f->format == AV_PIX_FMT_CUDA) {
                // Fill device surface metadata for downstream GPU preproc (NV12 fast path)
                bool device_ok = false;
                if (f->hw_frames_ctx) {
                    auto* hwfc = reinterpret_cast<AVHWFramesContext*>(f->hw_frames_ctx->data);
                    if (hwfc && hwfc->sw_format == AV_PIX_FMT_NV12 && f->data[0] && f->data[1]) {
                        frame.has_device_surface = true;
                        frame.device.on_gpu = true;
                        frame.device.fmt = va::core::PixelFormat::NV12;
                        frame.device.width = f->width;
                        frame.device.height = f->height;
                        frame.device.data0 = f->data[0];
                        frame.device.data1 = f->data[1];
                        frame.device.pitch0 = f->linesize[0];
                        frame.device.pitch1 = f->linesize[1];
                        device_ok = true;
                    }
                }
                if (device_ok) {
                    // Zero-copy preferred path: do not materialize CPU BGR when device NV12 is present.
                    frame.width = f->width;
                    frame.height = f->height;
                    frame.pts_ms = va::core::ms_now();
                    ok = true;
                    break;
                }
                // Fallback: transfer to CPU when device surface is not usable
                if (av_hwframe_transfer_data(sw, f, 0) < 0) {
                    continue;
                }
                src = sw;
            }

            // CPU fallback path: convert to BGR for downstream CPU renderer/encoder
            if (!sws_) {
                sws_ = sws_getContext(src->width, src->height, static_cast<AVPixelFormat>(src->format),
                                       src->width, src->height, AV_PIX_FMT_BGR24,
                                       SWS_BILINEAR, nullptr, nullptr, nullptr);
                if (!sws_) { continue; }
            }
            frame.width = src->width; frame.height = src->height; frame.pts_ms = va::core::ms_now();
            frame.bgr.resize(static_cast<size_t>(frame.width) * frame.height * 3u);
            uint8_t* dst_data[4] = { frame.bgr.data(), nullptr, nullptr, nullptr };
            int dst_linesize[4] = { frame.width * 3, 0, 0, 0 };
            sws_scale(sws_, src->data, src->linesize, 0, src->height, dst_data, dst_linesize);
            ok = true;
            break;
        }
        if (ok) break;
    }
    av_frame_free(&f);
    av_frame_free(&sw);
    return ok;
#endif
}

std::shared_ptr<ISwitchableSource> makeNvdecSource(const std::string& uri) {
    return std::make_shared<NvdecRtspSource>(uri);
}

} // namespace va::media
