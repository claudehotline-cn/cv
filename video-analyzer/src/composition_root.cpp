#include "composition_root.hpp"

#include "analyzer/analyzer.hpp"
#include "analyzer/model_session_factory.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"
#include "analyzer/preproc_letterbox_cuda.hpp"
#include "analyzer/postproc_yolo_det.hpp"
#include "analyzer/postproc_yolo_seg.hpp"
#include "analyzer/postproc_detr.hpp"
#include "analyzer/renderer_passthrough.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include "analyzer/renderer_overlay_cuda.hpp"
#include "core/engine_manager.hpp"
#include <filesystem>
#include "media/encoder_h264_ffmpeg.hpp"
#if defined(USE_CUDA) && defined(WITH_NVDEC)
#include "media/source_nvdec_cuda.hpp"
#endif
#include "media/source_switchable_rtsp.hpp"
#include "media/source_ffmpeg_rtsp.hpp"
#include "media/transport_webrtc_datachannel.hpp"

#include "core/logger.hpp"
// unified CUDA stream
#include "exec/stream_pool.hpp"
// NodeContext structure reused for factory hints
#include "analyzer/multistage/interfaces.hpp"

#include "analyzer/multistage/runner.hpp"
#include "analyzer/multistage/builder_yaml.hpp"
#include "analyzer/multistage/registry.hpp"
#include "analyzer/multistage/node_preproc_letterbox.hpp"
#include "analyzer/multistage/node_model.hpp"
#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/multistage/node_overlay.hpp"
#include "analyzer/multistage/node_roi_batch.hpp"
#include "analyzer/multistage/node_roi_batch_cuda.hpp"
#include "analyzer/multistage/node_kpt_decode.hpp"
#include "analyzer/multistage/node_overlay_kpt.hpp"
#include "analyzer/multistage/node_join.hpp"
#include "analyzer/multistage/node_reid_smooth.hpp"
#include <algorithm>
#include <cstdlib>

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
        auto toLower2 = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        auto findBool = [&](const char* key){
            const auto eng = engine_manager.currentEngine();
            auto it = eng.options.find(key);
            if (it == eng.options.end()) return false;
            auto v = toLower2(it->second);
            return v=="1"||v=="true"||v=="yes"||v=="on";
        };
#ifdef USE_FFMPEG
        // Explicit FFmpeg source switch
        const char* use_ffsrc = std::getenv("VA_USE_FFMPEG_SOURCE");
        const bool ffsrc_flag = findBool("use_ffmpeg_source") || (use_ffsrc && (std::string(use_ffsrc) == "1" || std::string(use_ffsrc) == "true"));
        if (ffsrc_flag) {
            VA_LOG_C(::va::core::LogLevel::Info, "composition") << "FFmpeg RTSP source selected for URI " << cfg.uri;
            try {
                return std::static_pointer_cast<va::media::ISwitchableSource>(
                    std::make_shared<va::media::FfmpegRtspSource>(cfg.uri));
            } catch (const std::exception& ex) {
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "FFmpeg source construction threw: " << ex.what() << ", fallback to other sources.";
            } catch (...) {
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "FFmpeg source construction unknown error, fallback.";
            }
        }
#endif
#ifdef USE_CUDA
#if defined(WITH_NVDEC)
        // Opt-in via environment to avoid surprising runtime changes
        const char* use_nvdec = std::getenv("VA_USE_NVDEC");
        const bool nvdec_flag = findBool("use_nvdec") || (use_nvdec && (std::string(use_nvdec) == "1" || std::string(use_nvdec) == "true"));
        if (nvdec_flag) {
        VA_LOG_C(::va::core::LogLevel::Info, "composition") << "NVDEC preferred for URI " << cfg.uri;
            try {
                if (auto src = va::media::makeNvdecSource(cfg.uri)) {
                    VA_LOG_C(::va::core::LogLevel::Info, "composition") << "NVDEC source constructed.";
                    return src;
                }
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "NVDEC makeNvdecSource returned null, fallback to CPU source.";
            } catch (const std::exception& ex) {
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "NVDEC source construction threw: " << ex.what() << ", fallback to CPU source.";
            } catch (...) {
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "NVDEC source construction unknown error, fallback to CPU source.";
            }
        }
#endif // WITH_NVDEC
#endif // USE_CUDA
        VA_LOG_C(::va::core::LogLevel::Info, "composition") << "using OpenCV RTSP source for URI " << cfg.uri;
        return std::static_pointer_cast<va::media::ISwitchableSource>(
            std::make_shared<va::media::SwitchableRtspSource>(cfg.uri));
    };

    factories.make_filter = [&engine_manager](const va::core::FilterConfig& cfg) {
        auto toLower2 = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        auto findBoolMs = [&](const char* key, bool defv){
            auto eng = engine_manager.currentEngine(); auto it = eng.options.find(key);
            if (it == eng.options.end()) return defv; auto v = toLower2(it->second);
            return v=="1"||v=="true"||v=="yes"||v=="on";
        };
        // Opt-in multistage analyzer via engine option or environment
        const char* use_ms_env = std::getenv("VA_USE_MULTISTAGE");
        const bool use_ms = findBoolMs("use_multistage", false) || (use_ms_env && (std::string(use_ms_env)=="1"||std::string(use_ms_env)=="true"));
        if (use_ms) {
            // Build Multistage graph from YAML if provided, else fallback to a default chain
            VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Multistage analyzer enabled (via engine option/env).";
            // Always read from EngineManager (Application has resolved multistage_yaml on startup if graph_id was set)
            auto eng_opts = engine_manager.currentEngine().options;
            using va::analyzer::multistage::AnalyzerMultistageAdapter;
            using va::analyzer::multistage::NodeRegistry;
            using va::analyzer::multistage::Graph;
            using va::analyzer::multistage::NodePreprocLetterbox;
            using va::analyzer::multistage::NodeModel;
            using va::analyzer::multistage::NodeNmsYolo;
            using va::analyzer::multistage::NodeOverlay;
            using va::analyzer::multistage::NodeRoiBatch;
            using va::analyzer::multistage::NodeKptDecode;
            using va::analyzer::multistage::NodeOverlayKpt;
            using va::analyzer::multistage::NodeRoiBatchCuda;
            using va::analyzer::multistage::NodeJoin;
            using va::analyzer::multistage::NodeReidSmooth;
            MS_REGISTER_NODE("preproc.letterbox", NodePreprocLetterbox);
            MS_REGISTER_NODE("model.ort", NodeModel);
            MS_REGISTER_NODE("post.yolo.nms", NodeNmsYolo);
            MS_REGISTER_NODE("overlay.cuda", NodeOverlay);
            va::analyzer::multistage::NodeRegistry::instance().reg("overlay.cpu", [](const std::unordered_map<std::string,std::string>& cfg){ return std::make_shared<NodeOverlay>(cfg); });
            MS_REGISTER_NODE("roi.batch", NodeRoiBatch);
            MS_REGISTER_NODE("roi.batch.cuda", NodeRoiBatchCuda);
            MS_REGISTER_NODE("post.yolo.kpt", NodeKptDecode);
            MS_REGISTER_NODE("overlay.kpt", NodeOverlayKpt);
            MS_REGISTER_NODE("join", NodeJoin);
            MS_REGISTER_NODE("reid.smooth", NodeReidSmooth);
            auto ms = std::make_shared<AnalyzerMultistageAdapter>();
            // Populate NodeContext with available process-wide services
            {
                auto& ctx = ms->context();
                ctx.logger = &::va::core::Logger::instance();
                // Streams and pools: leave null by default; nodes may manage internal pools.
                // Optionally expose engine manager as registry for future extensibility.
                ctx.engine_registry = &engine_manager;
            }
            // Configure shared buffer pools for multistage (use engine options if provided)
            {
                auto findSize = [&](const char* key, std::size_t fallback){
                    auto it = eng_opts.find(key);
                    if (it == eng_opts.end()) return fallback;
                    try { long long vv = std::stoll(it->second); return vv>0 ? static_cast<std::size_t>(vv) : fallback; }
                    catch (...) { return fallback; }
                };
                std::size_t dev_bytes = findSize("io_binding_input_bytes", 16ull*1024ull*1024ull);
                std::size_t host_bytes = findSize("io_binding_output_bytes", 16ull*1024ull*1024ull);
                ms->configurePools(host_bytes, 8, dev_bytes, 4);
            }
            // Apply overlay tuning from engine options (parity with single-stage path)
            {
                auto set_env = [](const char* key, const std::string& val){
#ifdef _WIN32
                    _putenv_s(key, val.c_str());
#else
                    setenv(key, val.c_str(), 1);
#endif
                };
                if (auto it = eng_opts.find("overlay_thickness"); it != eng_opts.end()) {
                    set_env("VA_OVERLAY_THICKNESS", it->second);
                }
                if (auto it = eng_opts.find("overlay_alpha"); it != eng_opts.end()) {
                    set_env("VA_OVERLAY_ALPHA", it->second);
                }
                if (auto it = eng_opts.find("overlay_draw_labels"); it != eng_opts.end()) {
                    std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                    bool enabled = !(v=="0"||v=="false"||v=="no"||v=="off");
                    set_env("VA_OVERLAY_DRAW_LABELS", enabled ? std::string("1") : std::string("0"));
                }
                // Logging level/throttle bridging from engine options to env (used by logging_util.hpp)
                auto set_if = [&](const char* opt_key, const char* env_key){ if (auto it = eng_opts.find(opt_key); it != eng_opts.end()) set_env(env_key, it->second); };
                set_if("log_throttle_ms", "VA_LOG_THROTTLE_MS");
                set_if("ms_log_throttle_ms", "VA_MS_LOG_THROTTLE_MS");
                set_if("overlay_log_throttle_ms", "VA_OVERLAY_LOG_THROTTLE_MS");
                set_if("yolo_log_throttle_ms", "VA_YOLO_LOG_THROTTLE_MS");
                set_if("log_throttled_level", "VA_LOG_THROTTLED_LEVEL");
                set_if("ms_log_level", "VA_MS_LOG_LEVEL");
                set_if("overlay_log_level", "VA_OVERLAY_LOG_LEVEL");
                set_if("yolo_log_level", "VA_YOLO_LOG_LEVEL");
            }
            // Try YAML
            std::string yaml_path;
            // 1) explicit absolute/relative file path override from engine options
            if (auto it = eng_opts.find("multistage_yaml"); it != eng_opts.end()) yaml_path = it->second;
            // 2) graph_id -> resolve under config/graphs directory near exe/cwd
            if (yaml_path.empty()) {
                auto itg = eng_opts.find("graph_id");
                if (itg != eng_opts.end()) {
                    const std::string graph_id = itg->second;
                    // Resolve config directory candidates (similar to Application::initialize)
                    std::vector<std::filesystem::path> candidates;
                    std::filesystem::path exe_dir = std::filesystem::current_path();
                    auto cwd_cfg = std::filesystem::current_path() / "config" / "graphs";
                    candidates.push_back(cwd_cfg);
                    candidates.push_back(exe_dir / "config" / "graphs");
                    auto cur = exe_dir;
                    for (int i=0;i<6;++i) {
                        candidates.push_back(cur / "config" / "graphs");
                        candidates.push_back(cur / "video-analyzer" / "config" / "graphs");
                        if (cur.has_parent_path()) cur = cur.parent_path(); else break;
                    }
                    std::error_code ec;
                    VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Graph search starting from cwd='" << std::filesystem::current_path().string() << "' graph_id='" << graph_id << "'";
                    for (const auto& dir : candidates) {
                        VA_LOG_C(::va::core::LogLevel::Debug, "composition") << "Graph search candidate dir: " << dir.string();
                    }
                    for (const auto& dir : candidates) {
                        auto file = dir / (graph_id + ".yaml");
                        if (std::filesystem::exists(file, ec)) { yaml_path = file.string(); break; }
                        auto file2 = dir / (graph_id + ".yml");
                        if (std::filesystem::exists(file2, ec)) { yaml_path = file2.string(); break; }
                    }
                    if (!yaml_path.empty()) {
                        VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Resolved graph YAML via graph_id at: " << yaml_path;
                    } else {
                        VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "Graph YAML not found via graph_id='" << graph_id << "' under cwd-config/graphs; will fallback or use default chain.";
                    }
                }
            }
            const char* yml_env = std::getenv("VA_MULTISTAGE_YAML");
            bool built = false;
            if (!yaml_path.empty()) {
                VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Loading multistage graph from YAML: " << yaml_path;
                built = va::analyzer::multistage::build_graph_from_yaml(yaml_path, ms->graph());
            } else if (yml_env) {
                std::string p = std::string(yml_env);
                VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Loading multistage graph from VA_MULTISTAGE_YAML: " << p;
                built = va::analyzer::multistage::build_graph_from_yaml(p, ms->graph());
            }
            if (!built) {
                // Fallback: pre -> model -> nms -> overlay
                VA_LOG_C(::va::core::LogLevel::Warn, "composition") << "Graph YAML not found or failed to load; using default multistage chain (pre->det->nms->ovl).";
                auto& g = ms->graph();
                int n0 = g.add_node("pre", std::make_shared<NodePreprocLetterbox>(std::unordered_map<std::string,std::string>{}), "preproc.letterbox", {});
                (void)n0;
                int n1 = g.add_node("det", std::make_shared<NodeModel>(std::unordered_map<std::string,std::string>{{"in","tensor:det_input"}}), "model.ort", {});
                int n2 = g.add_node("nms", std::make_shared<NodeNmsYolo>(std::unordered_map<std::string,std::string>{}), "post.yolo.nms", {});
                int n3 = g.add_node("ovl", std::make_shared<NodeOverlay>(std::unordered_map<std::string,std::string>{}), "overlay.cuda", {});
                g.add_edge("pre","det"); g.add_edge("det","nms"); g.add_edge("nms","ovl");
                g.finalize();
            } else {
                VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Multistage graph loaded successfully.";
            }
            return std::static_pointer_cast<va::analyzer::Analyzer>(ms);
        }
        auto analyzer = std::make_shared<va::analyzer::Analyzer>();

        auto engine_desc = engine_manager.currentEngine();
        const std::string provider_source = !cfg.engine_provider.empty() ? cfg.engine_provider : engine_desc.provider;
        const bool hint_gpu = (!provider_source.empty() && (provider_source.find("cuda") != std::string::npos || provider_source.find("trt") != std::string::npos))
                               || cfg.use_io_binding;

        std::shared_ptr<va::analyzer::IPreprocessor> preprocessor;
#ifdef USE_CUDA
        // Prefer CUDA preprocessor when GPU provider is active (zero-copy path),
        // unless explicitly disabled via engine option or env.
        auto toLower3 = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        // Default preference follows provider hint
        bool prefer_cuda_preproc = hint_gpu;
        // Engine option override (accepts true/false)
        if (!engine_desc.options.empty()) {
            auto it = engine_desc.options.find("use_cuda_preproc");
            if (it != engine_desc.options.end()) {
                std::string v = toLower3(it->second);
                if (v=="1"||v=="true"||v=="yes"||v=="on") prefer_cuda_preproc = true;
                else if (v=="0"||v=="false"||v=="no"||v=="off") prefer_cuda_preproc = false;
            }
        }
        // Environment override (VA_USE_CUDA_PREPROC=1/0)
        if (const char* env_cuda_pre = std::getenv("VA_USE_CUDA_PREPROC")) {
            std::string v = toLower3(env_cuda_pre);
            if (v=="1"||v=="true"||v=="yes"||v=="on") prefer_cuda_preproc = true;
            else if (v=="0"||v=="false"||v=="no"||v=="off") prefer_cuda_preproc = false;
        }
        if (prefer_cuda_preproc) {
            preprocessor = std::make_shared<va::analyzer::LetterboxPreprocessorCUDA>(cfg.input_width, cfg.input_height);
        }
#endif // USE_CUDA
        if (!preprocessor) {
            preprocessor = std::make_shared<va::analyzer::LetterboxPreprocessorCPU>(cfg.input_width, cfg.input_height);
        }
        analyzer->setPreprocessor(preprocessor);

        // Create model session via factory (decoupled from concrete provider)
        va::analyzer::multistage::NodeContext node_ctx; node_ctx.stream = va::exec::StreamPool::instance().tls();
        va::analyzer::ProviderDecision dec{};
        auto session = va::analyzer::create_model_session(engine_desc, node_ctx, &dec);

        const std::string& model_path = !cfg.model_path.empty() ? cfg.model_path : cfg.model_id;

        std::string provider_lower = provider_source;
        std::transform(provider_lower.begin(), provider_lower.end(), provider_lower.begin(), [](unsigned char c) {
            return static_cast<char>(std::tolower(c));
        });
        bool use_gpu = hint_gpu || provider_lower == "gpu";

        if (!session->loadModel(model_path, use_gpu)) {
            VA_LOG_C(::va::core::LogLevel::Error, "composition") << "failed to load model at " << model_path
                           << " (gpu=" << std::boolalpha << use_gpu << std::noboolalpha << ")";
            return std::shared_ptr<va::analyzer::Analyzer>{};
        }

        {
            auto runtime = session->getRuntimeInfo();
            va::core::EngineRuntimeStatus status;
            status.provider = runtime.provider;
            status.gpu_active = runtime.gpu_active;
            status.io_binding = runtime.io_binding;
            status.device_binding = runtime.device_binding;
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
            } else if (hint_gpu) {
                // 默认：当推理在 GPU（cuda/trt）时启用 GPU 叠加（无文字），无需显式配置
                auto renderer_cuda = std::make_shared<va::analyzer::OverlayRendererCUDA>();
                analyzer->setRenderer(renderer_cuda);
                set = true;
                VA_LOG_C(::va::core::LogLevel::Info, "composition") << "Using CUDA overlay by default (GPU provider detected)";
            }
#endif
            if (!set) {
                auto renderer = std::make_shared<va::analyzer::OverlayRendererCPU>();
                analyzer->setRenderer(renderer);
            }
        }

        // Overlay tuning via engine options -> environment bridge (used by renderers)
        {
            auto set_env = [](const char* key, const std::string& val){
#ifdef _WIN32
                _putenv_s(key, val.c_str());
#else
                setenv(key, val.c_str(), 1);
#endif
            };
            if (auto it = engine_desc.options.find("overlay_thickness"); it != engine_desc.options.end()) {
                set_env("VA_OVERLAY_THICKNESS", it->second);
            }
            if (auto it = engine_desc.options.find("overlay_alpha"); it != engine_desc.options.end()) {
                set_env("VA_OVERLAY_ALPHA", it->second);
            }
            if (auto it = engine_desc.options.find("overlay_draw_labels"); it != engine_desc.options.end()) {
                std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                bool enabled = !(v=="0"||v=="false"||v=="no"||v=="off");
                set_env("VA_OVERLAY_DRAW_LABELS", enabled ? std::string("1") : std::string("0"));
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
        auto toLower2 = [](std::string v){ std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);}); return v; };
        auto eng = engine_manager.currentEngine();
        bool prefer_nvenc = false;
        if (auto it = eng.options.find("use_nvenc"); it != eng.options.end()) {
            auto v = toLower2(it->second); prefer_nvenc = (v=="1"||v=="true"||v=="yes"||v=="on");
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
