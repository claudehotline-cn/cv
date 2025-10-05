#include "composition_root.hpp"

#include "analyzer/analyzer.hpp"
#include "analyzer/ort_session.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"
#include "analyzer/preproc_letterbox_cuda.hpp"
#include "analyzer/postproc_yolo_det.hpp"
#include "analyzer/postproc_yolo_seg.hpp"
#include "analyzer/postproc_detr.hpp"
#include "analyzer/renderer_passthrough.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include "analyzer/renderer_overlay_cuda.hpp"
#include "core/engine_manager.hpp"
#include "media/encoder_h264_ffmpeg.hpp"
#include "media/source_switchable_rtsp.hpp"
#include "media/source_ffmpeg_rtsp.hpp"
#include "media/transport_webrtc_datachannel.hpp"

#include "core/logger.hpp"

#include <algorithm>

// Forward declarations for optional factories (defined in va::media)
namespace va { namespace media {
    std::shared_ptr<ISwitchableSource> makeNvdecSource(const std::string& uri);
    std::shared_ptr<IEncoder> makeNvencEncoder(const va::core::EncoderConfig&);
} }

namespace va {

va::core::Factories buildFactories(va::core::EngineManager& engine_manager) {
    va::core::Factories factories;

    factories.make_source = [&engine_manager](const va::core::SourceConfig& cfg) -> std::shared_ptr<va::media::ISwitchableSource> {
        // Evaluate engine options at call time to support /api/engine/set hot switch
        auto toLower = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        auto findBool = [&](const char* key){
            const auto eng = engine_manager.currentEngine();
            auto it = eng.options.find(key);
            if (it == eng.options.end()) return false;
            auto v = toLower(it->second);
            return v=="1"||v=="true"||v=="yes"||v=="on";
        };
#ifdef USE_FFMPEG
        // Explicit FFmpeg source switch
        const char* use_ffsrc = std::getenv("VA_USE_FFMPEG_SOURCE");
        const bool ffsrc_flag = findBool("use_ffmpeg_source") || (use_ffsrc && (std::string(use_ffsrc) == "1" || std::string(use_ffsrc) == "true"));
        if (ffsrc_flag) {
            VA_LOG_INFO() << "[Factories] FFmpeg RTSP source selected for URI " << cfg.uri;
            try {
                return std::static_pointer_cast<va::media::ISwitchableSource>(
                    std::make_shared<va::media::FfmpegRtspSource>(cfg.uri));
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "[Factories] FFmpeg source construction threw: " << ex.what() << ", fallback to other sources.";
            } catch (...) {
                VA_LOG_WARN() << "[Factories] FFmpeg source construction unknown error, fallback.";
            }
        }
#endif
#ifdef USE_CUDA
#if defined(WITH_NVDEC)
        // Opt-in via environment to avoid surprising runtime changes
        const char* use_nvdec = std::getenv("VA_USE_NVDEC");
        const bool nvdec_flag = findBool("use_nvdec") || (use_nvdec && (std::string(use_nvdec) == "1" || std::string(use_nvdec) == "true"));
        if (nvdec_flag) {
            VA_LOG_INFO() << "[Factories] NVDEC preferred for URI " << cfg.uri;
            try {
                if (auto src = va::media::makeNvdecSource(cfg.uri)) {
                    VA_LOG_INFO() << "[Factories] NVDEC source constructed.";
                    return src;
                }
                VA_LOG_WARN() << "[Factories] NVDEC makeNvdecSource returned null, fallback to CPU source.";
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "[Factories] NVDEC source construction threw: " << ex.what() << ", fallback to CPU source.";
            } catch (...) {
                VA_LOG_WARN() << "[Factories] NVDEC source construction unknown error, fallback to CPU source.";
            }
        }
#endif // WITH_NVDEC
#endif // USE_CUDA
        VA_LOG_INFO() << "[Factories] using OpenCV RTSP source for URI " << cfg.uri;
        return std::static_pointer_cast<va::media::ISwitchableSource>(
            std::make_shared<va::media::SwitchableRtspSource>(cfg.uri));
    };

    factories.make_filter = [&engine_manager](const va::core::FilterConfig& cfg) {
        auto analyzer = std::make_shared<va::analyzer::Analyzer>();

        auto engine_desc = engine_manager.currentEngine();
        const std::string provider_source = !cfg.engine_provider.empty() ? cfg.engine_provider : engine_desc.provider;
        const bool hint_gpu = (!provider_source.empty() && (provider_source.find("cuda") != std::string::npos || provider_source.find("trt") != std::string::npos))
                               || cfg.use_io_binding;

        std::shared_ptr<va::analyzer::IPreprocessor> preprocessor;
#ifdef USE_CUDA
        // Enable CUDA preprocessor only when explicitly opted-in
        const char* use_cuda_preproc = std::getenv("VA_USE_CUDA_PREPROC");
        if (hint_gpu && use_cuda_preproc && (std::string(use_cuda_preproc) == "1" || std::string(use_cuda_preproc) == "true")) {
            preprocessor = std::make_shared<va::analyzer::LetterboxPreprocessorCUDA>(cfg.input_width, cfg.input_height);
        }
#endif // USE_CUDA
        if (!preprocessor) {
            preprocessor = std::make_shared<va::analyzer::LetterboxPreprocessorCPU>(cfg.input_width, cfg.input_height);
        }
        analyzer->setPreprocessor(preprocessor);

        auto session = std::make_shared<va::analyzer::OrtModelSession>();
#ifdef USE_ONNXRUNTIME
        va::analyzer::OrtModelSession::Options options;
        options.provider = !cfg.engine_provider.empty() ? cfg.engine_provider : engine_desc.provider;
        options.device_id = cfg.device_index;
        options.use_io_binding = cfg.use_io_binding;
        options.prefer_pinned_memory = cfg.prefer_pinned_memory;
        options.allow_cpu_fallback = cfg.allow_cpu_fallback;
        options.enable_profiling = cfg.enable_profiling;
        options.tensorrt_fp16 = cfg.tensorrt_fp16;
        options.tensorrt_int8 = cfg.tensorrt_int8;
        options.tensorrt_workspace_mb = cfg.tensorrt_workspace_mb;
        options.tensorrt_max_partition_iterations = cfg.tensorrt_max_partition_iterations;
        options.tensorrt_min_subgraph_size = cfg.tensorrt_min_subgraph_size;
        options.io_binding_input_bytes = cfg.io_binding_input_bytes;
        options.io_binding_output_bytes = cfg.io_binding_output_bytes;
        // Optional IoBinding staging controls via engine options map
        auto toLower = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return static_cast<char>(std::tolower(c));}); return v; };
        auto findBool = [&](const char* key, bool fallback){
            auto it = engine_desc.options.find(key);
            if (it == engine_desc.options.end()) return fallback;
            std::string v = toLower(it->second);
            if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
            if (v=="0"||v=="false"||v=="no"||v=="off") return false;
            return fallback;
        };
        auto findSize = [&](const char* key, std::size_t fallback){
            auto it = engine_desc.options.find(key);
            if (it == engine_desc.options.end()) return fallback;
            try { long long vv = std::stoll(it->second); return vv>0 ? static_cast<std::size_t>(vv) : fallback; }
            catch (...) { return fallback; }
        };
        options.stage_device_outputs = findBool("stage_device_outputs", options.stage_device_outputs);
        options.tensor_host_pool_bytes = findSize("tensor_host_pool_bytes", options.tensor_host_pool_bytes);
        options.device_output_views = findBool("device_output_views", options.device_output_views);
        session->setOptions(options);
#endif

        const std::string& model_path = !cfg.model_path.empty() ? cfg.model_path : cfg.model_id;

        std::string provider_lower = provider_source;
        std::transform(provider_lower.begin(), provider_lower.end(), provider_lower.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        bool use_gpu = hint_gpu || provider_lower == "gpu";

        if (!session->loadModel(model_path, use_gpu)) {
            VA_LOG_ERROR() << "[Factories] failed to load model at " << model_path
                           << " (gpu=" << std::boolalpha << use_gpu << std::noboolalpha << ")";
            return std::shared_ptr<va::analyzer::Analyzer>{};
        }

        {
            auto runtime = session->runtimeInfo();
            va::core::EngineRuntimeStatus status;
            status.provider = runtime.provider;
            status.gpu_active = runtime.gpu_active;
            status.io_binding = runtime.io_binding_active;
            status.device_binding = runtime.device_binding_active;
            status.cpu_fallback = runtime.cpu_fallback;
            engine_manager.updateRuntimeStatus(std::move(status));
        }

        analyzer->setSession(session);
        analyzer->setUseGpuHint(use_gpu);

        auto findBoolOpt = [&](const char* key, bool fallback){
            auto it = engine_desc.options.find(key);
            if (it == engine_desc.options.end()) return fallback;
            std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);});
            if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
            if (v=="0"||v=="false"||v=="no"||v=="off") return false;
            return fallback;
        };

        std::shared_ptr<va::analyzer::IPostprocessor> postprocessor;
        if (cfg.task == "seg") {
            postprocessor = std::make_shared<va::analyzer::YoloSegmentationPostprocessor>();
        } else if (cfg.task == "detr") {
            postprocessor = std::make_shared<va::analyzer::DetrPostprocessor>();
        } else {
            bool use_cuda_nms_flag = findBoolOpt("use_cuda_nms", false);
            const char* use_cuda_nms = std::getenv("VA_USE_CUDA_NMS");
#ifdef USE_CUDA
            if (use_cuda_nms_flag || (use_cuda_nms && (std::string(use_cuda_nms)=="1" || std::string(use_cuda_nms)=="true"))) {
                postprocessor = std::make_shared<va::analyzer::YoloDetectionPostprocessorCUDA>();
            }
#endif
            if (!postprocessor) {
                postprocessor = std::make_shared<va::analyzer::YoloDetectionPostprocessor>();
            }
        }
        analyzer->setPostprocessor(postprocessor);

        // Rendering selection: default CPU overlay; allow passthrough or CUDA
        bool render_cuda_flag = findBoolOpt("render_cuda", false);
        bool render_passthrough_flag = findBoolOpt("render_passthrough", false);
        const char* passthrough = std::getenv("VA_RENDER_PASSTHROUGH");
        const char* render_cuda = std::getenv("VA_RENDER_CUDA");
        if (render_passthrough_flag || (passthrough && (std::string(passthrough) == "1" || std::string(passthrough) == "true"))) {
            auto renderer = std::make_shared<va::analyzer::PassthroughRenderer>();
            analyzer->setRenderer(renderer);
        } else {
            bool set = false;
#ifdef USE_CUDA
            if (render_cuda_flag || (render_cuda && (std::string(render_cuda)=="1" || std::string(render_cuda)=="true"))) {
                auto renderer_cuda = std::make_shared<va::analyzer::OverlayRendererCUDA>();
                analyzer->setRenderer(renderer_cuda);
                set = true;
            }
#endif
            if (!set) {
                auto renderer = std::make_shared<va::analyzer::OverlayRendererCPU>();
                analyzer->setRenderer(renderer);
            }
        }

        auto params = std::make_shared<va::analyzer::AnalyzerParams>();
        params->confidence_threshold = cfg.confidence_threshold;
        params->iou_threshold = cfg.iou_threshold;
        analyzer->updateParams(std::move(params));

        return analyzer;
    };

    factories.make_encoder = [&engine_manager](const va::core::EncoderConfig& cfg) -> std::shared_ptr<va::media::IEncoder> {
#if defined(USE_CUDA) && defined(WITH_NVENC)
        auto toLower = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        auto eng = engine_manager.currentEngine();
        bool prefer_nvenc = false;
        if (auto it = eng.options.find("use_nvenc"); it != eng.options.end()) {
            auto v = toLower(it->second); prefer_nvenc = (v=="1"||v=="true"||v=="yes"||v=="on");
        }
        const char* use_nvenc = std::getenv("VA_USE_NVENC");
        if (prefer_nvenc || (use_nvenc && (std::string(use_nvenc) == "1" || std::string(use_nvenc) == "true"))) {
            if (auto enc = va::media::makeNvencEncoder(cfg)) {
                return enc;
            }
        }
#endif
        return std::static_pointer_cast<va::media::IEncoder>(
            std::make_shared<va::media::FfmpegH264Encoder>());
    };

    factories.make_transport = [](const va::core::TransportConfig& /*cfg*/) {
        auto transport = std::make_shared<va::media::WebRTCDataChannelTransport>();
        return transport;
    };

    return factories;
}

} // namespace va
