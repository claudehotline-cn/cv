#include "core/pipeline_builder.hpp"

#include "analyzer/analyzer.hpp"
#include "media/encoder.hpp"
#include "media/source.hpp"
#include "media/source_switchable_rtsp.hpp"
#include "media/source_ffmpeg_rtsp.hpp"
#if defined(USE_CUDA) && defined(WITH_NVDEC)
#include "media/source_nvdec_cuda.hpp"
#endif
#include "media/encoder_h264_ffmpeg.hpp"
#include "media/transport.hpp"

#include "core/logger.hpp"

namespace va::core {

PipelineBuilder::PipelineBuilder(const Factories& factories, EngineManager& engine_manager)
    : factories_(factories), engine_manager_(engine_manager) {}

std::shared_ptr<Pipeline> PipelineBuilder::build(const SourceConfig& source_cfg,
                                                 const FilterConfig& filter_cfg,
                                                 const EncoderConfig& encoder_cfg,
                                                 const TransportConfig& transport_cfg) const {
    VA_LOG_INFO() << "[PipelineBuilder] building pipeline stream=" << source_cfg.stream_id
                  << " profile=" << filter_cfg.profile_id
                  << " uri=" << source_cfg.uri
                  << " model=" << filter_cfg.model_id;

    std::shared_ptr<va::media::ISwitchableSource> source;
    std::shared_ptr<va::analyzer::Analyzer> analyzer;
    std::shared_ptr<va::media::IEncoder> encoder;
    std::shared_ptr<va::media::ITransport> transport;

    // Optional hard bypasses to diagnose crashes inside make_source functor
    auto parse_bool_env = [](const char* name){ const char* v = std::getenv(name); if (!v) return false; std::string s(v); for (auto& c : s) c = (char)std::tolower(c); return s=="1"||s=="true"||s=="yes"||s=="on"; };
    const bool force_ffmpeg_src = parse_bool_env("VA_FORCE_FFMPEG_SOURCE");
    const bool force_opencv_src = parse_bool_env("VA_FORCE_OPENCV_SOURCE");

    if (force_ffmpeg_src) {
        VA_LOG_WARN() << "[PipelineBuilder] VA_FORCE_FFMPEG_SOURCE=1 -> forcing FFmpeg RTSP source";
        source = std::static_pointer_cast<va::media::ISwitchableSource>(
            std::make_shared<va::media::FfmpegRtspSource>(source_cfg.uri));
        VA_LOG_INFO() << "[PipelineBuilder] source (forced FFmpeg) created.";
    } else if (force_opencv_src) {
        VA_LOG_WARN() << "[PipelineBuilder] VA_FORCE_OPENCV_SOURCE=1 -> forcing OpenCV RTSP source";
        source = std::static_pointer_cast<va::media::ISwitchableSource>(
            std::make_shared<va::media::SwitchableRtspSource>(source_cfg.uri));
        VA_LOG_INFO() << "[PipelineBuilder] source (forced OpenCV) created.";
    } else {
        try {
            VA_LOG_INFO() << "[PipelineBuilder] creating source...";
            source = factories_.make_source ? factories_.make_source(source_cfg) : nullptr;
            VA_LOG_INFO() << "[PipelineBuilder] source created.";
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "[PipelineBuilder] exception creating source: " << ex.what();
            return nullptr;
        } catch (...) {
            VA_LOG_ERROR() << "[PipelineBuilder] unknown exception creating source";
            return nullptr;
        }
    }

    try {
        VA_LOG_INFO() << "[PipelineBuilder] creating analyzer...";
        analyzer = factories_.make_filter ? factories_.make_filter(filter_cfg) : nullptr;
        VA_LOG_INFO() << "[PipelineBuilder] analyzer created.";
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "[PipelineBuilder] exception creating analyzer: " << ex.what();
        return nullptr;
    } catch (...) {
        VA_LOG_ERROR() << "[PipelineBuilder] unknown exception creating analyzer";
        return nullptr;
    }

    try {
        VA_LOG_INFO() << "[PipelineBuilder] creating encoder...";
        encoder = factories_.make_encoder ? factories_.make_encoder(encoder_cfg) : nullptr;
        VA_LOG_INFO() << "[PipelineBuilder] encoder created.";
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "[PipelineBuilder] exception creating encoder: " << ex.what();
        return nullptr;
    } catch (...) {
        VA_LOG_ERROR() << "[PipelineBuilder] unknown exception creating encoder";
        return nullptr;
    }

    try {
        VA_LOG_INFO() << "[PipelineBuilder] creating transport...";
        transport = factories_.make_transport ? factories_.make_transport(transport_cfg) : nullptr;
        VA_LOG_INFO() << "[PipelineBuilder] transport created.";
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "[PipelineBuilder] exception creating transport: " << ex.what();
        return nullptr;
    } catch (...) {
        VA_LOG_ERROR() << "[PipelineBuilder] unknown exception creating transport";
        return nullptr;
    }

    if (!source) {
        VA_LOG_ERROR() << "[PipelineBuilder] failed to create source for URI " << source_cfg.uri;
        return nullptr;
    }
    if (!analyzer) {
        VA_LOG_ERROR() << "[PipelineBuilder] failed to create analyzer for model " << filter_cfg.model_id;
        return nullptr;
    }
    if (!encoder) {
        VA_LOG_ERROR() << "[PipelineBuilder] failed to create encoder for stream " << source_cfg.stream_id;
        return nullptr;
    }
    if (!transport) {
        VA_LOG_ERROR() << "[PipelineBuilder] failed to create transport for stream " << source_cfg.stream_id;
        return nullptr;
    }

    (void)engine_manager_; // future use for binding execution providers

    va::media::IEncoder::Settings encoder_settings;
    encoder_settings.width = encoder_cfg.width;
    encoder_settings.height = encoder_cfg.height;
    encoder_settings.fps = encoder_cfg.fps;
    encoder_settings.bitrate_kbps = encoder_cfg.bitrate_kbps;
    encoder_settings.gop = encoder_cfg.gop;
    encoder_settings.bframes = encoder_cfg.bframes;
    encoder_settings.zero_latency = encoder_cfg.zero_latency;
    encoder_settings.preset = encoder_cfg.preset;
    encoder_settings.tune = encoder_cfg.tune;
    encoder_settings.profile = encoder_cfg.profile;
    encoder_settings.codec = encoder_cfg.codec;

    // If NVDEC source is used, pass its CUDA hwdevice to FFmpeg encoder to align contexts
#if defined(USE_CUDA) && defined(WITH_NVDEC)
    if (source && encoder) {
        if (auto nvdec_src = std::dynamic_pointer_cast<va::media::NvdecRtspSource>(source)) {
            if (auto ffenc = std::dynamic_pointer_cast<va::media::FfmpegH264Encoder>(encoder)) {
#ifdef USE_FFMPEG
                if (auto dev = nvdec_src->hwDeviceCtx()) {
                    ffenc->setExternalHwDevice(dev);
                }
#endif
            }
        }
    }
#endif

    VA_LOG_INFO() << "[PipelineBuilder] opening encoder w=" << encoder_settings.width
                  << " h=" << encoder_settings.height
                  << " fps=" << encoder_settings.fps
                  << " codec=" << encoder_settings.codec;
    if (!encoder->open(encoder_settings)) {
        VA_LOG_ERROR() << "[PipelineBuilder] encoder open failed for stream " << source_cfg.stream_id
                       << " (" << encoder_settings.width << "x" << encoder_settings.height << "@" << encoder_settings.fps
                       << ", codec=" << encoder_settings.codec << ")";
        return nullptr;
    }
    VA_LOG_INFO() << "[PipelineBuilder] encoder opened.";

    const std::string endpoint = transport_cfg.whip_url.empty() ? std::string() : transport_cfg.whip_url;
    VA_LOG_INFO() << "[PipelineBuilder] connecting transport endpoint='" << endpoint << "'";
    if (!transport->connect(endpoint)) {
        VA_LOG_ERROR() << "[PipelineBuilder] transport connect failed";
        return nullptr;
    }
    VA_LOG_INFO() << "[PipelineBuilder] transport connected.";

    auto pipeline = std::make_shared<Pipeline>(std::move(source),
                                               std::move(analyzer),
                                               std::move(encoder),
                                               std::move(transport),
                                               source_cfg.stream_id,
                                               filter_cfg.profile_id);
    VA_LOG_INFO() << "[PipelineBuilder] pipeline created stream=" << source_cfg.stream_id
                  << " profile=" << filter_cfg.profile_id
                  << " uri=" << source_cfg.uri;

    // Summarize runtime path (provider/GPU/IoBinding) and key engine toggles for quick diagnosis
    try {
        const auto runtime = engine_manager_.currentRuntimeStatus();
        const auto engine  = engine_manager_.currentEngine();
        auto getOpt = [&](const char* k){ auto it = engine.options.find(k); return it!=engine.options.end()? it->second : std::string(); };
        const std::string s_nvdec = getOpt("use_nvdec");
        const std::string s_nvenc = getOpt("use_nvenc");
        const std::string s_iob   = getOpt("use_io_binding");
        const std::string s_rcuda = getOpt("render_cuda");
        const std::string s_rpass = getOpt("render_passthrough");
        VA_LOG_INFO() << "[RuntimeSummary] provider=" << runtime.provider
                      << " gpu_active=" << std::boolalpha << runtime.gpu_active
                      << " io_binding=" << runtime.io_binding
                      << " device_binding=" << runtime.device_binding
                      << " nvdec=" << (s_nvdec.empty()?"":s_nvdec)
                      << " nvenc=" << (s_nvenc.empty()?"":s_nvenc)
                      << " io_bind_opt=" << (s_iob.empty()?"":s_iob)
                      << " overlay(cuda=" << (s_rcuda.empty()?"":s_rcuda) << ", passthrough=" << (s_rpass.empty()?"":s_rpass) << ")";
    } catch (...) {
        // ignore summary failures
    }
    return pipeline;
}

} // namespace va::core
