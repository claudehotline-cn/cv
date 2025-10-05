#include "media/encoder_h264_ffmpeg.hpp"

#include <algorithm>
#include <cctype>

#include <opencv2/core.hpp>

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
        return false;
    }

    codec_ctx_ = avcodec_alloc_context3(codec);
    if (!codec_ctx_) {
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
        // FFmpeg NVENC options
        const char* preset = settings.preset.empty() ? "p5" : settings.preset.c_str();
        av_opt_set(codec_ctx_->priv_data, "preset", preset, 0);
        if (settings.zero_latency) {
            av_opt_set(codec_ctx_->priv_data, "rc-lookahead", "0", 0);
            av_opt_set(codec_ctx_->priv_data, "delay", "0", 0);
        }
        if (!settings.profile.empty()) {
            av_opt_set(codec_ctx_->priv_data, "profile", settings.profile.c_str(), 0);
        }
    }

    if (avcodec_open2(codec_ctx_, codec, nullptr) < 0) {
        close();
        return false;
    }

    frame_ = av_frame_alloc();
    packet_ = av_packet_alloc();
    if (!frame_ || !packet_) {
        close();
        return false;
    }

    frame_->format = codec_ctx_->pix_fmt;
    frame_->width = codec_ctx_->width;
    frame_->height = codec_ctx_->height;
    if (av_frame_get_buffer(frame_, 32) < 0) {
        close();
        return false;
    }

    sws_ctx_ = sws_getContext(settings.width,
                              settings.height,
                              AV_PIX_FMT_BGR24,
                              settings.width,
                              settings.height,
                              AV_PIX_FMT_YUV420P,
                              SWS_BILINEAR,
                              nullptr,
                              nullptr,
                              nullptr);
    if (!sws_ctx_) {
        close();
        return false;
    }

    width_ = settings.width;
    height_ = settings.height;
    fps_ = settings.fps;
    pts_ = 0;
    opened_ = true;
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

bool FfmpegH264Encoder::encode(const core::Frame& frame, Packet& out_packet) {
#ifdef USE_FFMPEG
    if (!opened_ || !codec_ctx_ || !frame_) {
        if (!use_jpeg_) {
            return false;
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

    const uint8_t* src_slices[1] = { frame.bgr.data() };
    int src_stride[1] = { frame.width * 3 };
    sws_scale(sws_ctx_, src_slices, src_stride, 0, height_, frame_->data, frame_->linesize);

    frame_->pts = pts_++;

    int ret = avcodec_send_frame(codec_ctx_, frame_);
    if (ret < 0) {
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
        return false;
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
#endif
    width_ = 0;
    height_ = 0;
    fps_ = 0;
    pts_ = 0;
    use_jpeg_ = false;
    opened_ = false;
}

} // namespace va::media
