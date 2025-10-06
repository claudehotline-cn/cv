#include "media/encoder_h264_ffmpeg.hpp"

#include <algorithm>
#include <cctype>

#include <opencv2/core.hpp>
#include "core/logger.hpp"
#include "core/global_metrics.hpp"
#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_HAS_CUDA_RUNTIME 1
#    else
#      define VA_HAS_CUDA_RUNTIME 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_HAS_CUDA_RUNTIME 1
#  endif
#else
#  define VA_HAS_CUDA_RUNTIME 0
#endif

#ifdef USE_FFMPEG
#include <stdexcept>
#endif

namespace va::media {

#ifdef USE_FFMPEG
#ifndef FF_PROFILE_UNKNOWN
#define FF_PROFILE_UNKNOWN (-99)
#endif
#ifndef FF_PROFILE_H264_BASELINE
#define FF_PROFILE_H264_BASELINE 66
#endif
#ifndef FF_PROFILE_H264_CONSTRAINED_BASELINE
#define FF_PROFILE_H264_CONSTRAINED_BASELINE 578
#endif
#ifndef FF_PROFILE_H264_MAIN
#define FF_PROFILE_H264_MAIN 77
#endif
#ifndef FF_PROFILE_H264_HIGH
#define FF_PROFILE_H264_HIGH 100
#endif
#endif

FfmpegH264Encoder::FfmpegH264Encoder() = default;
FfmpegH264Encoder::~FfmpegH264Encoder() = default;

bool FfmpegH264Encoder::open(const Settings& settings) {
#ifdef USE_FFMPEG
    close();

    std::string codec_name = settings.codec;
    if (codec_name.empty()) {
        codec_name = "h264";
    }
    std::string codec_lower = codec_name;
    std::transform(codec_lower.begin(), codec_lower.end(), codec_lower.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });

    if (codec_lower == "jpeg" || codec_lower == "jpg" || codec_lower == "mjpeg") {
        VA_LOG_INFO() << "[Encoder] using JPEG passthrough mode "
                      << settings.width << "x" << settings.height << "@" << settings.fps;
        use_jpeg_ = true;
        width_ = settings.width;
        height_ = settings.height;
        fps_ = settings.fps;
        pts_ = 0;
        opened_ = true;
        return true;
    }

    use_jpeg_ = false;

    const AVCodec* codec = nullptr;
    AVCodecID codec_id = AV_CODEC_ID_H264;
    if (codec_lower == "h265" || codec_lower == "hevc") {
        codec_id = AV_CODEC_ID_H265;
        codec = avcodec_find_encoder_by_name("libx265");
        if (!codec) {
            codec = avcodec_find_encoder(codec_id);
        }
    } else {
        // Try explicit encoder name first (e.g., h264_nvenc)
        if (!codec_lower.empty()) {
            const AVCodec* by_name = avcodec_find_encoder_by_name(codec_lower.c_str());
            if (by_name) {
                codec = by_name;
            }
        }
        if (!codec) {
            codec = avcodec_find_encoder_by_name("libx264");
        }
        if (!codec) {
            codec = avcodec_find_encoder_by_name("libopenh264");
        }
        if (!codec) {
            codec = avcodec_find_encoder(codec_id);
        }
    }
    if (!codec) {
        VA_LOG_ERROR() << "[Encoder] failed to find encoder for codec=" << codec_name;
        return false;
    }

    codec_ctx_ = avcodec_alloc_context3(codec);
    if (!codec_ctx_) {
        VA_LOG_ERROR() << "[Encoder] avcodec_alloc_context3 failed";
        return false;
    }

    codec_ctx_->thread_count = 1;
    codec_ctx_->width = settings.width;
    codec_ctx_->height = settings.height;
    codec_ctx_->time_base = AVRational{1, settings.fps};
    codec_ctx_->framerate = AVRational{settings.fps, 1};
    codec_ctx_->gop_size = settings.gop > 0 ? settings.gop : settings.fps * 2;
    codec_ctx_->max_b_frames = settings.bframes;
    codec_ctx_->pix_fmt = AV_PIX_FMT_YUV420P;
    codec_ctx_->bit_rate = static_cast<int64_t>(settings.bitrate_kbps) * 1000;

    std::string encoder_name = codec && codec->name ? codec->name : "";

    VA_LOG_INFO() << "[Encoder] selected encoder name='" << encoder_name << "'";
    if (encoder_name == "libx264") {
        const char* preset = settings.preset.empty() ? "veryfast" : settings.preset.c_str();
        av_opt_set(codec_ctx_->priv_data, "preset", preset, 0);
        const char* tune = settings.tune.empty() ? (settings.zero_latency ? "zerolatency" : "") : settings.tune.c_str();
        if (tune && *tune) {
            av_opt_set(codec_ctx_->priv_data, "tune", tune, 0);
        }
        if (!settings.profile.empty()) {
            av_opt_set(codec_ctx_->priv_data, "profile", settings.profile.c_str(), 0);
        }
    } else if (encoder_name.find("nvenc") != std::string::npos) {
        // NVENC mapping: translate x264-style preset/tune to NVENC-safe options
        auto toLower = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){ return (char)std::tolower(c); }); return v; };
        std::string preset_in = toLower(settings.preset);
        const char* nv_preset = "p4"; // default balanced
        if (preset_in == "ultrafast" || preset_in == "superfast") nv_preset = "p1";
        else if (preset_in == "veryfast") nv_preset = "p3";
        else if (preset_in == "faster" || preset_in == "fast") nv_preset = "p4";
        else if (preset_in == "medium") nv_preset = "p5";
        else if (preset_in == "slow") nv_preset = "p6";
        else if (preset_in == "slower" || preset_in == "veryslow") nv_preset = "p7";
        // If user already passed NVENC preset like p1..p7, keep it
        if (preset_in.size() == 2 && preset_in[0] == 'p' && preset_in[1] >= '1' && preset_in[1] <= '7') {
            nv_preset = settings.preset.c_str();
        }
        av_opt_set(codec_ctx_->priv_data, "preset", nv_preset, 0);
        av_opt_set(codec_ctx_->priv_data, "rc", "cbr", 0);
        if (settings.zero_latency) {
            // NVENC low-latency settings
            av_opt_set(codec_ctx_->priv_data, "rc-lookahead", "0", 0);
            av_opt_set(codec_ctx_->priv_data, "delay", "0", 0);
        }
        VA_LOG_INFO() << "[Encoder][nvenc] mapped preset=" << nv_preset
                      << " rc=cbr" << (settings.zero_latency ? " lookahead=0 delay=0" : "");
        if (!settings.profile.empty()) {
            av_opt_set(codec_ctx_->priv_data, "profile", settings.profile.c_str(), 0);
        }
    } else if (encoder_name == "libopenh264") {
        if (settings.zero_latency) {
            av_opt_set(codec_ctx_->priv_data, "skip_frame", "default", 0);
            av_opt_set(codec_ctx_->priv_data, "allow_skip_frames", "1", 0);
        }
        if (!settings.profile.empty()) {
            int profile_value = FF_PROFILE_UNKNOWN;
            if (settings.profile == "baseline") {
                profile_value = FF_PROFILE_H264_BASELINE;
            } else if (settings.profile == "constrained_baseline") {
                profile_value = FF_PROFILE_H264_CONSTRAINED_BASELINE;
            } else if (settings.profile == "main") {
                profile_value = FF_PROFILE_H264_MAIN;
            } else if (settings.profile == "high") {
                profile_value = FF_PROFILE_H264_HIGH;
            }
            if (profile_value != FF_PROFILE_UNKNOWN) {
                codec_ctx_->profile = profile_value;
                av_opt_set_int(codec_ctx_->priv_data, "profile", profile_value, 0);
            }
        }
        // libopenh264 ignores unknown profiles; avoid setting unsupported ones
    } else if (encoder_name.find("nvenc") != std::string::npos) {
        // FFmpeg NVENC: prepare CUDA hwframes; mapping already applied above
        // Use NV12 for NVENC path
        codec_ctx_->pix_fmt = AV_PIX_FMT_NV12;
        // Try to adopt external CUDA hwdevice (from NVDEC) or create our own
        AVBufferRef* device = nullptr;
#ifdef USE_FFMPEG
        if (external_hw_device_ctx_) {
            hw_device_ctx_ = av_buffer_ref(reinterpret_cast<AVBufferRef*>(external_hw_device_ctx_));
        } else if (av_hwdevice_ctx_create(&device, AV_HWDEVICE_TYPE_CUDA, nullptr, nullptr, 0) == 0) {
            hw_device_ctx_ = device;
        }
        if (hw_device_ctx_) {
            AVBufferRef* frames_ref = av_hwframe_ctx_alloc(hw_device_ctx_);
            if (frames_ref) {
                AVHWFramesContext* frames_ctx = (AVHWFramesContext*)frames_ref->data;
                frames_ctx->format = AV_PIX_FMT_CUDA;
                frames_ctx->sw_format = codec_ctx_->pix_fmt; // NV12
                frames_ctx->width = settings.width;
                frames_ctx->height = settings.height;
                // Increase hwframe pool to reduce EAGAIN backpressure under burst
                frames_ctx->initial_pool_size = 8;
                if (av_hwframe_ctx_init(frames_ref) == 0) {
                    hw_frames_ctx_ = frames_ref;
                    codec_ctx_->hw_frames_ctx = av_buffer_ref(hw_frames_ctx_);
                    use_hwframes_ = true;
                    VA_LOG_INFO() << "[Encoder][nvenc] using CUDA hwframes (NV12) (" << (external_hw_device_ctx_?"external":"internal") << ")";
                } else {
                    av_buffer_unref(&frames_ref);
                }
            }
        }
#endif
    }

    VA_LOG_INFO() << "[Encoder] avcodec_open2 w=" << codec_ctx_->width
                  << " h=" << codec_ctx_->height
                  << " fps=" << codec_ctx_->framerate.num << "/" << codec_ctx_->framerate.den
                  << " pix_fmt=" << (int)codec_ctx_->pix_fmt;
    if (avcodec_open2(codec_ctx_, codec, nullptr) < 0) {
        VA_LOG_ERROR() << "[Encoder] avcodec_open2 failed";
        close();
        return false;
    }

    frame_ = av_frame_alloc();
    packet_ = av_packet_alloc();
    if (!frame_ || !packet_) {
        VA_LOG_ERROR() << "[Encoder] av_frame_alloc/av_packet_alloc failed";
        close();
        return false;
    }

    frame_->format = codec_ctx_->pix_fmt;
    frame_->width = codec_ctx_->width;
    frame_->height = codec_ctx_->height;
    if (av_frame_get_buffer(frame_, 32) < 0) {
        VA_LOG_ERROR() << "[Encoder] av_frame_get_buffer failed";
        close();
        return false;
    }

    // Select target sws format by encoder pix_fmt (YUV420P or NV12)
    enum AVPixelFormat dst_fmt = codec_ctx_->pix_fmt == AV_PIX_FMT_NV12 ? AV_PIX_FMT_NV12 : AV_PIX_FMT_YUV420P;
    sws_ctx_ = sws_getContext(settings.width,
                              settings.height,
                              AV_PIX_FMT_BGR24,
                              settings.width,
                              settings.height,
                              dst_fmt,
                              SWS_BILINEAR,
                              nullptr,
                              nullptr,
                              nullptr);
    if (!sws_ctx_) {
        VA_LOG_ERROR() << "[Encoder] sws_getContext failed";
        close();
        return false;
    }

    width_ = settings.width;
    height_ = settings.height;
    fps_ = settings.fps;
    pts_ = 0;
    opened_ = true;
    VA_LOG_INFO() << "[Encoder] open OK (codec='" << encoder_name << "')";
    return true;
#else
    (void)settings;
    opened_ = true;
    use_jpeg_ = true;
    width_ = settings.width;
    height_ = settings.height;
    fps_ = settings.fps;
    pts_ = 0;
    return true;
#endif
}

bool FfmpegH264Encoder::encode(const va::core::Frame& frame, Packet& out_packet) {
#ifdef USE_FFMPEG
    if (!opened_ || !codec_ctx_ || !frame_) {
        if (!use_jpeg_) {
            return false;
        }
    }

    // Light pre-drain: pull at most one pending packet to reduce encoder backpressure
    {
        int r = avcodec_receive_packet(codec_ctx_, packet_);
        if (r == 0) {
            // discard pre-drained packet here; this is just to keep the pipeline flowing
            av_packet_unref(packet_);
        }
    }

    if (use_jpeg_) {
        if (frame.bgr.empty() || frame.width <= 0 || frame.height <= 0) {
            return false;
        }

        width_ = frame.width;
        height_ = frame.height;

        const cv::Mat image(height_, width_, CV_8UC3, const_cast<uint8_t*>(frame.bgr.data()));
        std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, jpeg_quality_};
        if (!cv::imencode(".jpg", image, out_packet.data, params)) {
            return false;
        }
        out_packet.keyframe = true;
        out_packet.pts_ms = frame.pts_ms;
        return true;
    }

    if (frame.width != width_ || frame.height != height_) {
        return false;
    }

    bool fed_device_nv12 = false;
    bool attempted_d2d = false;
    static int dbg_send_ctr = 0;
#if VA_HAS_CUDA_RUNTIME
    // Preferred D2D path: if upstream provided an FFmpeg HW frame (e.g., NVDEC), use av_hwframe_transfer_data
    if (use_hwframes_ && hw_frames_ctx_ && frame.hw_frame) {
        AVFrame* src_hw = reinterpret_cast<AVFrame*>(frame.hw_frame.get());
        if (src_hw && src_hw->format == AV_PIX_FMT_CUDA) {
            AVFrame* hwf = av_frame_alloc();
            if (hwf) {
                hwf->format = AV_PIX_FMT_CUDA;
                hwf->width = frame_->width;
                hwf->height = frame_->height;
                hwf->hw_frames_ctx = av_buffer_ref(hw_frames_ctx_);
                if (av_hwframe_get_buffer(hw_frames_ctx_, hwf, 0) >= 0) {
                    if (av_hwframe_transfer_data(hwf, src_hw, 0) == 0) {
                        attempted_d2d = true;
                        hwf->pts = pts_++;
                        int sret = avcodec_send_frame(codec_ctx_, hwf);
                        if (sret == 0) {
                            fed_device_nv12 = true;
                        } else if (sret == AVERROR(EAGAIN)) {
                            va::core::GlobalMetrics::eagain_retry_count.fetch_add(1, std::memory_order_relaxed);
                            int rret = 0; int drained = 0;
                            while ((rret = avcodec_receive_packet(codec_ctx_, packet_)) == 0) {
                                av_packet_unref(packet_);
                                ++drained;
                            }
                            if (drained > 0) {
                                sret = avcodec_send_frame(codec_ctx_, hwf);
                                if (sret == 0) {
                                    fed_device_nv12 = true;
                                }
                            }
                        } else {
                            if (((++dbg_send_ctr) % 100) == 1) {
                                VA_LOG_DEBUG() << "[Encoder][nvenc] avcodec_send_frame(hw xfer) ret=" << sret;
                            }
                        }
                    }
                }
                av_frame_free(&hwf);
            }
        }
    }

    // Fallback D2D path: copy raw NV12 device pointers into NVENC hwframe when provided
    if (!fed_device_nv12 && use_hwframes_ && hw_frames_ctx_ && frame.has_device_surface && frame.device.on_gpu &&
        frame.device.fmt == va::core::PixelFormat::NV12 && frame.device.data0 && frame.device.data1) {
        AVFrame* hwf = av_frame_alloc();
        if (hwf) {
            hwf->format = AV_PIX_FMT_CUDA;
            hwf->width = frame_->width;
            hwf->height = frame_->height;
            hwf->hw_frames_ctx = av_buffer_ref(hw_frames_ctx_);
            if (av_hwframe_get_buffer(hw_frames_ctx_, hwf, 0) >= 0) {
                uint8_t* dstY = hwf->data[0];
                uint8_t* dstUV = hwf->data[1];
                const uint8_t* srcY = static_cast<const uint8_t*>(frame.device.data0);
                const uint8_t* srcUV = static_cast<const uint8_t*>(frame.device.data1);
                const size_t srcPitchY = static_cast<size_t>(frame.device.pitch0);
                const size_t srcPitchUV = static_cast<size_t>(frame.device.pitch1);
                const size_t dstPitchY = static_cast<size_t>(hwf->linesize[0]);
                const size_t dstPitchUV = static_cast<size_t>(hwf->linesize[1]);
                cudaError_t e1 = cudaMemcpy2D(dstY, dstPitchY, srcY, srcPitchY,
                                              static_cast<size_t>(frame.width), static_cast<size_t>(frame.height),
                                              cudaMemcpyDeviceToDevice);
                if (e1 == cudaSuccess) {
                    cudaError_t e2 = cudaMemcpy2D(dstUV, dstPitchUV, srcUV, srcPitchUV,
                                                  static_cast<size_t>(frame.width), static_cast<size_t>(frame.height) / 2,
                                                  cudaMemcpyDeviceToDevice);
                    if (e2 == cudaSuccess) {
                        attempted_d2d = true;
                        hwf->pts = pts_++;
                        int sret = avcodec_send_frame(codec_ctx_, hwf);
                        if (sret == 0) {
                            fed_device_nv12 = true;
                        } else if (sret == AVERROR(EAGAIN)) {
                            // Drain pending packets then retry once
                            va::core::GlobalMetrics::eagain_retry_count.fetch_add(1, std::memory_order_relaxed);
                            int rret = 0; int drained = 0;
                            while ((rret = avcodec_receive_packet(codec_ctx_, packet_)) == 0) {
                                av_packet_unref(packet_);
                                ++drained;
                            }
                            if (drained > 0) {
                                sret = avcodec_send_frame(codec_ctx_, hwf);
                                if (sret == 0) {
                                    fed_device_nv12 = true;
                                }
                            }
                        } else {
                            // limited debug for rare non-EAGAIN error
                            if (((++dbg_send_ctr) % 100) == 1) {
                                VA_LOG_DEBUG() << "[Encoder][nvenc] avcodec_send_frame(D2D) ret=" << sret;
                            }
                        }
                    }
                }
            }
            av_frame_free(&hwf);
        }
    }
#endif

    if (!fed_device_nv12) {
        // Guard: in NVDEC zero-copy path, there may be no CPU BGR. Avoid noisy sws_scale warnings.
        if (frame.bgr.empty() || frame.width <= 0 || frame.height <= 0) {
            if (frame.has_device_surface && frame.device.on_gpu && frame.device.fmt == va::core::PixelFormat::NV12 &&
                frame.device.data0 && frame.device.data1) {
                // Device->Host NV12 fallback (keeps pipeline producing packets without BGR)
                const uint8_t* srcY = static_cast<const uint8_t*>(frame.device.data0);
                const uint8_t* srcUV = static_cast<const uint8_t*>(frame.device.data1);
                const size_t srcPitchY = static_cast<size_t>(frame.device.pitch0);
                const size_t srcPitchUV = static_cast<size_t>(frame.device.pitch1);
                const size_t dstPitchY = static_cast<size_t>(frame_->linesize[0]);
                const size_t dstPitchUV = static_cast<size_t>(frame_->linesize[1]);
                (void)cudaMemcpy2D(frame_->data[0], dstPitchY, srcY, srcPitchY,
                                   static_cast<size_t>(frame.width), static_cast<size_t>(frame.height),
                                   cudaMemcpyDeviceToHost);
                (void)cudaMemcpy2D(frame_->data[1], dstPitchUV, srcUV, srcPitchUV,
                                   static_cast<size_t>(frame.width), static_cast<size_t>(frame.height) / 2,
                                   cudaMemcpyDeviceToHost);
                va::core::GlobalMetrics::cpu_fallback_skips.fetch_add(1, std::memory_order_relaxed);
            } else {
                // no viable fallback; drain once and skip packet
                VA_LOG_DEBUG() << "[Encoder] skip CPU upload: no BGR for fallback (device NV12 frame)";
                int r = avcodec_receive_packet(codec_ctx_, packet_);
                if (r == 0) { av_packet_unref(packet_); }
                va::core::GlobalMetrics::cpu_fallback_skips.fetch_add(1, std::memory_order_relaxed);
                out_packet.data.clear();
                out_packet.keyframe = false;
                out_packet.pts_ms = frame.pts_ms;
                return true;
            }
        } else {
            const uint8_t* src_slices[1] = { frame.bgr.data() };
            int src_stride[1] = { frame.width * 3 };
            sws_scale(sws_ctx_, src_slices, src_stride, 0, height_, frame_->data, frame_->linesize);
        }
    }

    frame_->pts = pts_++;

    int ret = 0;
    if (!fed_device_nv12 && use_hwframes_ && hw_frames_ctx_) {
        // Allocate a device frame and upload
        AVFrame* hwf = av_frame_alloc();
        if (!hwf) return false;
        hwf->format = AV_PIX_FMT_CUDA;
        hwf->width = frame_->width;
        hwf->height = frame_->height;
        hwf->hw_frames_ctx = av_buffer_ref(hw_frames_ctx_);
        if (av_hwframe_get_buffer(hw_frames_ctx_, hwf, 0) < 0) {
            av_frame_free(&hwf);
            return false;
        }
        if (av_hwframe_transfer_data(hwf, frame_, 0) < 0) {
            av_frame_free(&hwf);
            return false;
        }
        ret = avcodec_send_frame(codec_ctx_, hwf);
        av_frame_free(&hwf);
    } else if (!fed_device_nv12) {
        ret = avcodec_send_frame(codec_ctx_, frame_);
    }
    if (ret < 0) {
        VA_LOG_DEBUG() << "[Encoder] avcodec_send_frame failed ret=" << ret << (fed_device_nv12? " (device NV12)":" (CPU upload)");
        return false;
    }

    ret = avcodec_receive_packet(codec_ctx_, packet_);
    if (ret == AVERROR(EAGAIN) || ret == AVERROR_EOF) {
        out_packet.data.clear();
        out_packet.keyframe = false;
        out_packet.pts_ms = frame.pts_ms;
        return true;
    }
    if (ret < 0) {
        VA_LOG_DEBUG() << "[Encoder] avcodec_receive_packet failed ret=" << ret;
        return false;
    }

    if (attempted_d2d) {
        va::core::GlobalMetrics::d2d_nv12_frames.fetch_add(1, std::memory_order_relaxed);
    }

    out_packet.data.assign(packet_->data, packet_->data + packet_->size);
    out_packet.keyframe = (packet_->flags & AV_PKT_FLAG_KEY) != 0;
    out_packet.pts_ms = frame.pts_ms;
    av_packet_unref(packet_);
    return true;
#else
    if (!opened_) {
        return false;
    }
    if (frame.bgr.empty() || frame.width <= 0 || frame.height <= 0) {
        return false;
    }
    width_ = frame.width;
    height_ = frame.height;
    const cv::Mat image(height_, width_, CV_8UC3, const_cast<uint8_t*>(frame.bgr.data()));
    std::vector<int> params{cv::IMWRITE_JPEG_QUALITY, jpeg_quality_};
    if (!cv::imencode(".jpg", image, out_packet.data, params)) {
        return false;
    }
    out_packet.keyframe = true;
    out_packet.pts_ms = frame.pts_ms;
    return true;
#endif
}

void FfmpegH264Encoder::close() {
#ifdef USE_FFMPEG
    if (packet_) {
        av_packet_free(&packet_);
        packet_ = nullptr;
    }
    if (frame_) {
        av_frame_free(&frame_);
        frame_ = nullptr;
    }
    if (codec_ctx_) {
        avcodec_free_context(&codec_ctx_);
        codec_ctx_ = nullptr;
    }
    if (sws_ctx_) {
        sws_freeContext(sws_ctx_);
        sws_ctx_ = nullptr;
    }
    if (hw_frames_ctx_) { av_buffer_unref(&hw_frames_ctx_); hw_frames_ctx_ = nullptr; }
    if (hw_device_ctx_) { av_buffer_unref(&hw_device_ctx_); hw_device_ctx_ = nullptr; }
#endif
    width_ = 0;
    height_ = 0;
    fps_ = 0;
    pts_ = 0;
    use_jpeg_ = false;
    opened_ = false;
}

} // namespace va::media

