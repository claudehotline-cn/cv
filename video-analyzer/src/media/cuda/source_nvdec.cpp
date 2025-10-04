#include "media/cuda/source_nvdec.hpp"

#include "core/logger.hpp"

extern "C" {
#include <libswscale/swscale.h>
}

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_NVDEC_HAS_CUDA 1
#    else
#      define VA_NVDEC_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_NVDEC_HAS_CUDA 1
#  endif
#else
#  define VA_NVDEC_HAS_CUDA 0
#endif

namespace {

AVPixelFormat get_hw_format(AVCodecContext* ctx, const AVPixelFormat* pix_fmts) {
    for (const AVPixelFormat* p = pix_fmts; *p != AV_PIX_FMT_NONE; ++p) {
        if (*p == AV_PIX_FMT_CUDA) {
            return *p;
        }
    }
    VA_LOG_ERROR() << "[NVDEC] Failed to find CUDA pixel format.";
    return pix_fmts[0];
}

} // namespace

namespace va::media::cuda {

NvdecRtspSource::NvdecRtspSource(std::string uri)
    : uri_(std::move(uri)) {}

bool NvdecRtspSource::start() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (running_) {
        return true;
    }
    if (!open()) {
        close();
        return false;
    }
    running_ = true;
    frame_counter_ = 0;
    avg_latency_ms_ = 0.0;
    started_at_ = std::chrono::steady_clock::now();
    last_frame_time_ = started_at_;
    return true;
}

void NvdecRtspSource::stop() {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_) {
        return;
    }
    running_ = false;
    close();
}

bool NvdecRtspSource::read(core::Frame& frame) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (!running_) {
        return false;
    }

    const auto start_ts = std::chrono::steady_clock::now();
    if (!fetchFrame(frame)) {
        return false;
    }

    frame_counter_++;
    last_frame_time_ = std::chrono::steady_clock::now();
    const double latency_ms = std::chrono::duration_cast<std::chrono::microseconds>(last_frame_time_ - start_ts).count() / 1000.0;
    avg_latency_ms_ = avg_latency_ms_ + (latency_ms - avg_latency_ms_) / static_cast<double>(frame_counter_);
    return true;
}

SourceStats NvdecRtspSource::stats() const {
    std::lock_guard<std::mutex> lock(mutex_);
    SourceStats stats;
    const auto now = std::chrono::steady_clock::now();
    const double elapsed_ms = std::chrono::duration_cast<std::chrono::milliseconds>(now - started_at_).count();
    if (frame_counter_ > 0 && elapsed_ms > 0.0) {
        stats.fps = static_cast<double>(frame_counter_) * 1000.0 / elapsed_ms;
    }
    stats.avg_latency_ms = avg_latency_ms_;
    stats.last_frame_id = frame_counter_;
    return stats;
}

bool NvdecRtspSource::switchUri(const std::string& uri) {
    std::lock_guard<std::mutex> lock(mutex_);
    if (uri == uri_) {
        return true;
    }
    uri_ = uri;
    if (running_) {
        close();
        return open();
    }
    return true;
}

bool NvdecRtspSource::open() {
    if (avformat_open_input(&format_ctx_, uri_.c_str(), nullptr, nullptr) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to open input URI: " << uri_;
        return false;
    }
    if (avformat_find_stream_info(format_ctx_, nullptr) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to find stream info: " << uri_;
        return false;
    }

    video_stream_index_ = av_find_best_stream(format_ctx_, AVMEDIA_TYPE_VIDEO, -1, -1, nullptr, 0);
    if (video_stream_index_ < 0) {
        VA_LOG_ERROR() << "[NVDEC] No video stream found in URI: " << uri_;
        return false;
    }

    if (!initCodec()) {
        return false;
    }

    packet_ = av_packet_alloc();
    hw_frame_ = av_frame_alloc();
    sw_frame_ = av_frame_alloc();
    if (!packet_ || !hw_frame_ || !sw_frame_) {
        VA_LOG_ERROR() << "[NVDEC] Failed to allocate AVPacket/AVFrame.";
        return false;
    }

    av_read_play(format_ctx_);
    return true;
}

void NvdecRtspSource::close() {
    if (packet_) {
        av_packet_free(&packet_);
        packet_ = nullptr;
    }
    if (hw_frame_) {
        av_frame_free(&hw_frame_);
        hw_frame_ = nullptr;
    }
    if (sw_frame_) {
        av_frame_free(&sw_frame_);
        sw_frame_ = nullptr;
    }
    if (sws_ctx_) {
        sws_freeContext(sws_ctx_);
        sws_ctx_ = nullptr;
    }
    if (codec_ctx_) {
        avcodec_free_context(&codec_ctx_);
        codec_ctx_ = nullptr;
    }
    if (format_ctx_) {
        avformat_close_input(&format_ctx_);
        format_ctx_ = nullptr;
    }
    if (hw_device_ctx_) {
        av_buffer_unref(&hw_device_ctx_);
        hw_device_ctx_ = nullptr;
    }
    video_stream_index_ = -1;
    frame_buffer_.clear();
}

bool NvdecRtspSource::initCodec() {
    AVStream* stream = format_ctx_->streams[video_stream_index_];
    codec_ = avcodec_find_decoder(stream->codecpar->codec_id);
    if (!codec_) {
        VA_LOG_ERROR() << "[NVDEC] Decoder not found for codec id " << stream->codecpar->codec_id;
        return false;
    }

    codec_ctx_ = avcodec_alloc_context3(codec_);
    if (!codec_ctx_) {
        VA_LOG_ERROR() << "[NVDEC] Failed to allocate codec context.";
        return false;
    }

    if (avcodec_parameters_to_context(codec_ctx_, stream->codecpar) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to copy codec parameters.";
        return false;
    }

    codec_ctx_->get_format = get_hw_format;

    if (av_hwdevice_ctx_create(&hw_device_ctx_, AV_HWDEVICE_TYPE_CUDA, nullptr, nullptr, 0) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to create CUDA hwdevice context.";
        return false;
    }

    codec_ctx_->hw_device_ctx = av_buffer_ref(hw_device_ctx_);
    if (!codec_ctx_->hw_device_ctx) {
        VA_LOG_ERROR() << "[NVDEC] Failed to reference hwdevice context.";
        return false;
    }

    if (avcodec_open2(codec_ctx_, codec_, nullptr) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to open codec with NVDEC.";
        return false;
    }

    return true;
}

bool NvdecRtspSource::fetchFrame(core::Frame& frame) {
    while (true) {
        if (av_read_frame(format_ctx_, packet_) < 0) {
            return false;
        }

        if (packet_->stream_index != video_stream_index_) {
            av_packet_unref(packet_);
            continue;
        }

        if (avcodec_send_packet(codec_ctx_, packet_) < 0) {
            av_packet_unref(packet_);
            return false;
        }
        av_packet_unref(packet_);

        int ret = avcodec_receive_frame(codec_ctx_, hw_frame_);
        if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
            continue;
        } else if (ret < 0) {
            return false;
        }

        bool ok = transferFrame(hw_frame_, frame);
        av_frame_unref(hw_frame_);
        if (ok) {
            return true;
        }
    }
}

bool NvdecRtspSource::transferFrame(AVFrame* src, core::Frame& dst) {
    if (!src) {
        return false;
    }

    if (!sw_frame_) {
        sw_frame_ = av_frame_alloc();
        if (!sw_frame_) {
            VA_LOG_ERROR() << "[NVDEC] Failed to allocate sw_frame.";
            return false;
        }
    }

    sw_frame_->format = codec_ctx_->sw_pix_fmt;
    sw_frame_->width = codec_ctx_->width;
    sw_frame_->height = codec_ctx_->height;

    if (av_hwframe_transfer_data(sw_frame_, src, 0) < 0) {
        VA_LOG_ERROR() << "[NVDEC] Failed to transfer frame from GPU to CPU.";
        return false;
    }

    if (!sws_ctx_ || last_width_ != sw_frame_->width || last_height_ != sw_frame_->height || last_format_ != sw_frame_->format) {
        sws_ctx_ = sws_getCachedContext(sws_ctx_,
                                        sw_frame_->width,
                                        sw_frame_->height,
                                        static_cast<AVPixelFormat>(sw_frame_->format),
                                        sw_frame_->width,
                                        sw_frame_->height,
                                        AV_PIX_FMT_BGR24,
                                        SWS_BILINEAR,
                                        nullptr,
                                        nullptr,
                                        nullptr);
        if (!sws_ctx_) {
            VA_LOG_ERROR() << "[NVDEC] Failed to create sws context.";
            return false;
        }
        last_width_ = sw_frame_->width;
        last_height_ = sw_frame_->height;
        last_format_ = static_cast<AVPixelFormat>(sw_frame_->format);
    }

    if (!ensureFrameBuffer(sw_frame_->width, sw_frame_->height)) {
        return false;
    }

    uint8_t* dest_slices[3] = { frame_buffer_.data(), nullptr, nullptr };
    int dest_stride[3] = { sw_frame_->width * 3, 0, 0 };

    sws_scale(sws_ctx_,
              sw_frame_->data,
              sw_frame_->linesize,
              0,
              sw_frame_->height,
              dest_slices,
              dest_stride);

    dst.width = sw_frame_->width;
    dst.height = sw_frame_->height;
    const AVRational tb = format_ctx_->streams[video_stream_index_]->time_base;
    dst.pts_ms = sw_frame_->pts != AV_NOPTS_VALUE ? sw_frame_->pts * av_q2d(tb) * 1000.0 : 0.0;
    dst.bgr = frame_buffer_;

#if VA_NVDEC_HAS_CUDA
    const int width = sw_frame_->width;
    const int height = sw_frame_->height;
    const int chroma_height = height / 2;
    const std::size_t plane0_pitch = static_cast<std::size_t>(width);
    const std::size_t plane1_pitch = static_cast<std::size_t>(width);
    const std::size_t plane0_bytes = plane0_pitch * static_cast<std::size_t>(height);
    const std::size_t plane1_bytes = plane1_pitch * static_cast<std::size_t>(chroma_height);
    const std::size_t total_bytes = plane0_bytes + plane1_bytes;

    core::MemoryHandle device_handle;
    if (!prepareSurface(total_bytes, device_handle)) {
        av_frame_unref(sw_frame_);
        return true;
    }

    void* device_ptr = device_handle.device_ptr;
    cudaError_t copy_y = cudaMemcpy2D(device_ptr,
                                      plane0_pitch,
                                      sw_frame_->data[0],
                                      sw_frame_->linesize[0],
                                      plane0_pitch,
                                      height,
                                      cudaMemcpyDeviceToDevice);
    if (copy_y != cudaSuccess) {
        if (surface_pool_) {
            surface_pool_->release(std::move(device_handle));
        }
        av_frame_unref(sw_frame_);
        return true;
    }

    cudaError_t copy_uv = cudaMemcpy2D(static_cast<uint8_t*>(device_ptr) + plane0_bytes,
                                       plane1_pitch,
                                       sw_frame_->data[1],
                                       sw_frame_->linesize[1],
                                       plane1_pitch,
                                       chroma_height,
                                       cudaMemcpyDeviceToDevice);
    if (copy_uv != cudaSuccess) {
        if (surface_pool_) {
            surface_pool_->release(std::move(device_handle));
        }
        av_frame_unref(sw_frame_);
        return true;
    }

    device_handle.bytes = total_bytes;
    device_handle.pitch = plane0_pitch;
    device_handle.width = width;
    device_handle.height = height;
    device_handle.location = core::MemoryLocation::Device;
    device_handle.format = core::PixelFormat::NV12;
    device_handle.host_ptr = nullptr;
    device_handle.host_owner.reset();

    dst.surface.handle = std::move(device_handle);
    dst.surface.pts_ms = dst.pts_ms;
    dst.surface.width = width;
    dst.surface.height = height;
    dst.has_surface = true;
    if (surface_pool_) {
        auto weak_pool = std::weak_ptr<va::core::GpuBufferPool>(surface_pool_);
        dst.surface_recycle = [weak_pool](va::core::MemoryHandle&& handle) mutable {
            if (auto pool = weak_pool.lock()) {
                pool->release(std::move(handle));
            }
        };
    }
#else
    dst.surface = {};
    dst.has_surface = false;
#endif

    av_frame_unref(sw_frame_);
    return true;
}

bool NvdecRtspSource::ensureFrameBuffer(int width, int height) {
    const std::size_t required = static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3;
    if (frame_buffer_.size() != required) {
        frame_buffer_.resize(required);
    }
    return true;
}

bool NvdecRtspSource::prepareSurface(std::size_t total_bytes, va::core::MemoryHandle& handle) {
#if VA_NVDEC_HAS_CUDA
    handle = {};
    if (total_bytes == 0) {
        return false;
    }
    if (!surface_pool_ || surface_pool_bytes_ < total_bytes) {
        surface_pool_ = std::make_shared<va::core::GpuBufferPool>(total_bytes, 4);
        surface_pool_bytes_ = total_bytes;
    }
    auto mem = surface_pool_->acquire();
    if (!mem.device_ptr || mem.bytes < total_bytes) {
        surface_pool_->release(std::move(mem));
        return false;
    }
    mem.bytes = total_bytes;
    handle = std::move(mem);
    return true;
#else
    (void)total_bytes;
    handle = {};
    surface_pool_.reset();
    surface_pool_bytes_ = 0;
    return false;
#endif
}

} // namespace va::media::cuda


