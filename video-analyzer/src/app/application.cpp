#include "app/application.hpp"

#include "ConfigLoader.hpp"
#include "analyzer/analyzer.hpp"
#include "core/logger.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"
#include "core/nvdec_events.hpp"

#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
#include "control_plane_embedded/adapters/graph_adapter_yaml.hpp"
#include "control_plane_embedded/controllers/pipeline_controller.hpp"
#include "control_plane_embedded/api/grpc_server.hpp"
#endif

#if defined(USE_GRPC)
#include <grpcpp/grpcpp.h>
#include "source_control.grpc.pb.h"
#endif

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <filesystem>
#include <iostream>
#include <utility>
#include <vector>

#ifdef _WIN32
#include <windows.h>
#else
#include <unistd.h>
#endif

namespace va::app {

Application::Application() = default;
Application::~Application() {
    shutdown();
}

bool Application::initialize(const std::string& config_dir) {
    if (initialized_) {
        return true;
    }

    auto has_config_files = [](const std::filesystem::path& dir) {
        std::error_code e;
        if (dir.empty()) return false;
        auto app = dir / "app.yaml";
        auto profiles = dir / "profiles.yaml";
        return std::filesystem::exists(app, e) || std::filesystem::exists(profiles, e);
    };

    auto exe_dir = []() -> std::filesystem::path {
#ifdef _WIN32
        char buf[MAX_PATH];
        DWORD len = GetModuleFileNameA(nullptr, buf, MAX_PATH);
        if (len > 0) {
            return std::filesystem::path(buf).parent_path();
        }
#elif defined(__linux__)
        char buf[4096];
        ssize_t len = readlink("/proc/self/exe", buf, sizeof(buf) - 1);
        if (len > 0) { buf[len] = 0; return std::filesystem::path(buf).parent_path(); }
#endif
        return std::filesystem::current_path();
    }();

    // If user provided a config path, honor it strictly (do not auto-scan)
    if (!config_dir.empty()) {
        std::filesystem::path input(config_dir);
        std::error_code ec;
        std::filesystem::path chosen;
        if (std::filesystem::is_directory(input, ec)) {
            chosen = input;
        } else if (std::filesystem::is_regular_file(input, ec)) {
            chosen = input.parent_path();
        } else {
            chosen = input; // may be non-existing; check below
        }
        if (!has_config_files(chosen)) {
            last_error_ = std::string("config not found or missing required files in '") + chosen.string() + "'";
            VA_LOG_ERROR() << last_error_;
            return false;
        }
        config_dir_ = chosen.string();
        VA_LOG_INFO() << "Using user-provided config directory: '" << config_dir_ << "'";
    } else {
        // Build candidate config directories
        std::vector<std::filesystem::path> candidates;
        // 1) Environment override
        if (const char* env = std::getenv("VA_CONFIG_DIR")) {
            candidates.push_back(std::filesystem::path(env));
        }
        // 2) CWD/config
        candidates.push_back(std::filesystem::current_path() / "config");
        // 3) exe-dir relatives: ascend up to 5 levels and try "config" and "video-analyzer/config"
        {
            auto cur = exe_dir;
            for (int i = 0; i < 6; ++i) {
                candidates.push_back(cur / "config");
                candidates.push_back(cur / "video-analyzer" / "config");
                if (cur.has_parent_path()) cur = cur.parent_path(); else break;
            }
        }
        // Pick the first candidate that has config files
        std::filesystem::path resolved;
        for (const auto& c : candidates) {
            if (has_config_files(c)) { resolved = c; break; }
        }
        if (!resolved.empty()) {
            config_dir_ = resolved.string();
            VA_LOG_INFO() << "Resolved config directory: '" << config_dir_ << "'";
        } else {
            // Fallback to original behavior
            config_dir_ = "config";
            if (config_dir_.empty()) config_dir_ = ".";
            VA_LOG_WARN() << "Config directory not found via robust resolution; falling back to '" << config_dir_ << "'";
        }
    }

    last_error_.clear();

    factories_ = va::buildFactories(engine_manager_);
    pipeline_builder_ = std::make_unique<va::core::PipelineBuilder>(factories_, engine_manager_);
    track_manager_ = std::make_unique<va::core::TrackManager>(*pipeline_builder_);

    detection_models_ = ConfigLoader::loadDetectionModels(config_dir_);
    detection_model_index_.clear();
    active_models_by_task_.clear();
    for (const auto& model : detection_models_) {
        if (!model.id.empty()) {
            detection_model_index_.emplace(model.id, model);
        }
        if (!model.task.empty() && !model.id.empty() && !active_models_by_task_.count(model.task)) {
            active_models_by_task_.emplace(model.task, model.id);
        }
    }

    profiles_ = ConfigLoader::loadProfiles(config_dir_);
    profile_index_.clear();
    for (const auto& profile : profiles_) {
        if (!profile.name.empty()) {
            profile_index_.emplace(profile.name, profile);
        }
    }
    analyzer_params_ = ConfigLoader::loadAnalyzerParams(config_dir_);
    app_config_ = ConfigLoader::loadAppConfig(config_dir_);

    va::core::Logger::instance().configure(app_config_.observability);
    // Configure per-source metrics TTL (shard cleanup)
    try { va::core::DropMetrics::setTtlSeconds(app_config_.observability.metrics_ttl_seconds); } catch (...) {}
    try { va::core::SourceReconnects::setTtlSeconds(app_config_.observability.metrics_ttl_seconds); } catch (...) {}
    try { va::core::NvdecEvents::setTtlSeconds(app_config_.observability.metrics_ttl_seconds); } catch (...) {}

    va::core::EngineDescriptor descriptor;
    descriptor.name = app_config_.engine.type;
    std::string raw_provider = app_config_.engine.provider.empty() ? app_config_.engine.type : app_config_.engine.provider;
    std::string provider_lower = raw_provider;
    std::transform(provider_lower.begin(), provider_lower.end(), provider_lower.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    if (provider_lower == "ort-trt" || provider_lower == "ort_tensor_rt" || provider_lower == "ort-tensorrt") {
        raw_provider = "tensorrt";
    } else if (provider_lower == "ort-cuda" || provider_lower == "ort-gpu") {
        raw_provider = "cuda";
    } else if (provider_lower == "ort-cpu") {
        raw_provider = "cpu";
    }
    descriptor.provider = raw_provider;
    descriptor.device_index = app_config_.engine.device;
    descriptor.options["use_io_binding"] = app_config_.engine.options.use_io_binding ? "true" : "false";
    descriptor.options["prefer_pinned_memory"] = app_config_.engine.options.prefer_pinned_memory ? "true" : "false";
    descriptor.options["allow_cpu_fallback"] = app_config_.engine.options.allow_cpu_fallback ? "true" : "false";
    descriptor.options["enable_profiling"] = app_config_.engine.options.enable_profiling ? "true" : "false";
    // Source/encoder toggles (if provided in app.yaml)
    if (app_config_.engine.options.use_ffmpeg_source) {
        descriptor.options["use_ffmpeg_source"] = "true";
    }
    if (app_config_.engine.options.use_nvdec) {
        descriptor.options["use_nvdec"] = "true";
    }
    if (app_config_.engine.options.use_nvenc) {
        descriptor.options["use_nvenc"] = "true";
    }
    // Other toggles
    if (app_config_.engine.options.device_output_views) descriptor.options["device_output_views"] = "true";
    if (app_config_.engine.options.stage_device_outputs) descriptor.options["stage_device_outputs"] = "true";
    if (app_config_.engine.options.use_cuda_nms) descriptor.options["use_cuda_nms"] = "true";
    if (app_config_.engine.options.render_passthrough) descriptor.options["render_passthrough"] = "true";
    if (app_config_.engine.options.render_cuda) descriptor.options["render_cuda"] = "true";
    if (app_config_.engine.options.use_cuda_preproc) descriptor.options["use_cuda_preproc"] = "true";
    if (!app_config_.engine.options.warmup_runs.empty()) descriptor.options["warmup_runs"] = app_config_.engine.options.warmup_runs;
    if (app_config_.engine.options.overlay_thickness > 0) descriptor.options["overlay_thickness"] = std::to_string(app_config_.engine.options.overlay_thickness);
    if (app_config_.engine.options.overlay_alpha > 0.0) {
        char buf[32];
        std::snprintf(buf, sizeof(buf), "%.3f", app_config_.engine.options.overlay_alpha);
        descriptor.options["overlay_alpha"] = buf;
    }
    descriptor.options["trt_fp16"] = app_config_.engine.options.tensorrt_fp16 ? "true" : "false";
    descriptor.options["trt_int8"] = app_config_.engine.options.tensorrt_int8 ? "true" : "false";
    if (app_config_.engine.options.tensorrt_workspace_mb > 0) {
        descriptor.options["trt_workspace_mb"] = std::to_string(app_config_.engine.options.tensorrt_workspace_mb);
    }
    if (app_config_.engine.options.tensorrt_max_partition_iterations > 0) {
        descriptor.options["trt_max_partition_iterations"] = std::to_string(app_config_.engine.options.tensorrt_max_partition_iterations);
    }
    if (app_config_.engine.options.tensorrt_min_subgraph_size > 0) {
        descriptor.options["trt_min_subgraph_size"] = std::to_string(app_config_.engine.options.tensorrt_min_subgraph_size);
    }
    if (app_config_.engine.options.io_binding_input_bytes > 0) {
        descriptor.options["io_binding_input_bytes"] = std::to_string(app_config_.engine.options.io_binding_input_bytes);
    }
    if (app_config_.engine.options.io_binding_output_bytes > 0) {
        descriptor.options["io_binding_output_bytes"] = std::to_string(app_config_.engine.options.io_binding_output_bytes);
    }
    // Multistage: pass-through options from app.yaml
    if (app_config_.engine.options.use_multistage) {
        descriptor.options["use_multistage"] = "true";
    }
    if (!app_config_.engine.options.graph_id.empty()) {
        descriptor.options["graph_id"] = app_config_.engine.options.graph_id;
    }
    if (!app_config_.engine.options.multistage_yaml.empty()) {
        descriptor.options["multistage_yaml"] = app_config_.engine.options.multistage_yaml;
    }
    {
        const auto& o = app_config_.engine.options;
        VA_LOG_C(::va::core::LogLevel::Info, "app")
            << "[Startup] multistage use=" << std::boolalpha << o.use_multistage
            << " graph_id='" << (o.graph_id.empty()? std::string("") : o.graph_id) << "'"
            << " yaml='" << (o.multistage_yaml.empty()? std::string("") : o.multistage_yaml) << "'";
        // Also echo what will be pushed into EngineDescriptor options
        VA_LOG_C(::va::core::LogLevel::Info, "app")
            << "[Startup] engine.options keys:"
            << (descriptor.options.count("use_multistage")? " use_multistage" : "")
            << (descriptor.options.count("graph_id")? " graph_id" : "")
            << (descriptor.options.count("multistage_yaml")? " multistage_yaml" : "");
        // Resolve graph YAML path early using config_dir_ when only graph_id is provided
        try {
            bool use_ms = o.use_multistage || (descriptor.options.find("use_multistage")!=descriptor.options.end() && descriptor.options["use_multistage"]=="true");
            bool has_yaml = descriptor.options.find("multistage_yaml") != descriptor.options.end() && !descriptor.options["multistage_yaml"].empty();
            auto it_gid = descriptor.options.find("graph_id");
            if (use_ms && !has_yaml && it_gid != descriptor.options.end() && !it_gid->second.empty()) {
                std::filesystem::path base(config_dir_);
                std::filesystem::path gdir = base / "graphs";
                std::string gid = it_gid->second;
                std::error_code ec;
                std::filesystem::path p1 = gdir / (gid + ".yaml");
                std::filesystem::path p2 = gdir / (gid + ".yml");
                if (std::filesystem::exists(p1, ec)) {
                    auto can = std::filesystem::weakly_canonical(p1, ec);
                    descriptor.options["multistage_yaml"] = (ec? p1 : can).string();
                    VA_LOG_C(::va::core::LogLevel::Info, "app") << "[Startup] resolved graph YAML: " << descriptor.options["multistage_yaml"];
                } else if (std::filesystem::exists(p2, ec)) {
                    auto can = std::filesystem::weakly_canonical(p2, ec);
                    descriptor.options["multistage_yaml"] = (ec? p2 : can).string();
                    VA_LOG_C(::va::core::LogLevel::Info, "app") << "[Startup] resolved graph YAML: " << descriptor.options["multistage_yaml"];
                } else {
                    VA_LOG_C(::va::core::LogLevel::Warn, "app") << "[Startup] graph_id='" << gid << "' not found under '" << gdir.string() << "'";
                }
            }
        } catch (...) { /* best-effort */ }
    }

    // Bridge global logging throttle/level from engine.options into environment for early availability
    {
        auto set_env = [](const char* key, const std::string& val){
#ifdef _WIN32
            _putenv_s(key, val.c_str());
#else
            setenv(key, val.c_str(), 1);
#endif
        };
        auto set_if = [&](const char* opt_key, const char* env_key){ auto it = descriptor.options.find(opt_key); if (it != descriptor.options.end() && !it->second.empty()) set_env(env_key, it->second); };
        // Global defaults
        set_if("log_throttle_ms", "VA_LOG_THROTTLE_MS");
        set_if("log_throttled_level", "VA_LOG_THROTTLED_LEVEL");
        // Per-tag overrides
        set_if("ms_log_throttle_ms", "VA_MS_LOG_THROTTLE_MS");
        set_if("overlay_log_throttle_ms", "VA_OVERLAY_LOG_THROTTLE_MS");
        set_if("yolo_log_throttle_ms", "VA_YOLO_LOG_THROTTLE_MS");
        set_if("ms_log_level", "VA_MS_LOG_LEVEL");
        set_if("overlay_log_level", "VA_OVERLAY_LOG_LEVEL");
        set_if("yolo_log_level", "VA_YOLO_LOG_LEVEL");
    }

    engine_manager_.setEngine(std::move(descriptor));

    va::server::RestServerOptions rest_options;
    rest_options.host = "0.0.0.0";
    rest_options.port = 8082;
    // Allow overriding REST bind via environment for flexibility in multi-process dev
#ifdef _WIN32
    if (const char* p = std::getenv("VA_REST_HOST")) { rest_options.host = p; }
    if (const char* p = std::getenv("VA_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) rest_options.port = v; } catch (...) {} }
#else
    if (const char* p = std::getenv("VA_REST_HOST")) { rest_options.host = p; }
    if (const char* p = std::getenv("VA_REST_PORT")) { try { int v = std::stoi(p); if (v > 0 && v < 65536) rest_options.port = v; } catch (...) {} }
#endif
    rest_server_ = std::make_unique<va::server::RestServer>(rest_options, *this);

    initialized_ = true;
    return true;
}

bool Application::start() {
    if (!initialized_) {
        return false;
    }

    bool ok = true;
    if (rest_server_) {
        ok = rest_server_->start();
    }

#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
    // 控制平面：按 app.yaml 启动 gRPC（可由 env 覆盖）
    if (app_config_.control_plane.enabled) {
        try {
            // 构造适配器与控制器
            if (!graph_adapter_) {
                graph_adapter_.reset(reinterpret_cast<va::control::IGraphAdapter*>(new va::control::GraphAdapterYaml(&engine_manager_)));
            }
            if (!pipeline_controller_) {
                pipeline_controller_ = std::make_unique<va::control::PipelineController>(graph_adapter_.get());
            }
            std::string addr = app_config_.control_plane.grpc_addr.empty()? std::string("0.0.0.0:9090") : app_config_.control_plane.grpc_addr;
            if (const char* ep = std::getenv("VA_GRPC_ADDR")) { addr = ep; }
            grpc_server_ = va::control::StartGrpcServer(addr, pipeline_controller_.get(), this);
            if (!grpc_server_.get()) {
                VA_LOG_WARN() << "[ControlPlane] gRPC start failed at " << addr;
            } else {
                VA_LOG_INFO() << "[ControlPlane] gRPC started at " << addr;
            }
        } catch (const std::exception& ex) {
            VA_LOG_WARN() << "[ControlPlane] start error: " << ex.what();
        }
    }
#endif

    // Start VSM WatchState client if configured (Plan B)
#if defined(USE_GRPC)
    try { startVsmWatchIfConfigured(); } catch (...) { /* best-effort */ }
#endif

    return ok;
}

void Application::shutdown() {
    if (!initialized_) {
        return;
    }

    if (rest_server_) {
        rest_server_->stop();
        rest_server_.reset();
    }
#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
    grpc_server_.reset();
    pipeline_controller_.reset();
    graph_adapter_.reset();
#endif

#if defined(USE_GRPC)
    vsm_watch_stop_.store(true);
    if (vsm_watch_thread_ && vsm_watch_thread_->joinable()) {
        vsm_watch_thread_->join();
    }
    vsm_watch_thread_.reset();
#endif

    track_manager_.reset();
    pipeline_builder_.reset();

    initialized_ = false;
}

bool Application::isInitialized() const {
    return initialized_;
}

#if defined(USE_GRPC)
void Application::startVsmWatchIfConfigured() {
    std::string addr = app_config_.control_plane.vsm_addr;
    if (const char* ep = std::getenv("VA_VSM_ADDR")) { addr = ep; }
    if (addr.empty()) {
        return; // not configured
    }
    if (vsm_watch_thread_) return;

    // choose default profile
    auto default_profile = std::string{};
    for (const auto& p : profiles_) {
        if (p.name == "det_720p") { default_profile = p.name; break; }
    }
    if (default_profile.empty() && !profiles_.empty()) default_profile = profiles_.front().name;
    if (default_profile.empty()) default_profile = "det_720p";

    int interval_ms = app_config_.control_plane.watch_interval_ms;
    if (const char* v = std::getenv("VA_VSM_WATCH_MS")) { try { int t = std::stoi(v); if (t>0) interval_ms = t; } catch (...) {} }

    vsm_watch_stop_.store(false);
    vsm_watch_thread_ = std::make_unique<std::thread>([this, addr, default_profile, interval_ms]() {
        VA_LOG_INFO() << "[ControlPlane] VSM watch connecting addr=" << addr << " interval_ms=" << interval_ms;
        while (!vsm_watch_stop_.load()) {
            try {
                // gRPC channel with optional keepalive
                grpc::ChannelArguments args;
                auto env_int = [](const char* k, int defv){ if(const char* v=getenv(k)){ try { return std::stoi(v);} catch(...){} } return defv;};
                int ka_time = app_config_.control_plane.keepalive_time_ms; ka_time = env_int("VA_VSM_KEEPALIVE_TIME_MS", ka_time);
                int ka_timeout = app_config_.control_plane.keepalive_timeout_ms; ka_timeout = env_int("VA_VSM_KEEPALIVE_TIMEOUT_MS", ka_timeout);
                int ka_permit = app_config_.control_plane.keepalive_permit_without_calls ? 1 : 0; ka_permit = env_int("VA_VSM_KEEPALIVE_PERMIT_WITHOUT_CALLS", ka_permit);
                args.SetInt("grpc.keepalive_time_ms", ka_time);
                args.SetInt("grpc.keepalive_timeout_ms", ka_timeout);
                args.SetInt("grpc.keepalive_permit_without_calls", ka_permit);
                auto channel = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
                std::unique_ptr<vsm::v1::SourceControl::Stub> stub = vsm::v1::SourceControl::NewStub(channel);
                grpc::ClientContext ctx;
                // Set a generous deadline to detect dead streams
                int deadline_ms = app_config_.control_plane.watch_deadline_ms; deadline_ms = env_int("VA_VSM_WATCH_DEADLINE_MS", deadline_ms);
                auto ddl = std::chrono::system_clock::now() + std::chrono::milliseconds(deadline_ms);
                ctx.set_deadline(ddl);
                vsm::v1::WatchStateRequest req; req.set_interval_ms(interval_ms);
                std::unique_ptr<grpc::ClientReader<vsm::v1::WatchStateReply>> reader(stub->WatchState(&ctx, req));
                struct Item { std::string uri; std::string profile; std::string model; };
                std::unordered_map<std::string, Item> last; // attach_id -> {uri,profile,model}
                std::unordered_map<std::string, long long> last_change_ms;
                auto now_ms = [](){ return (long long)std::chrono::duration_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); };
                int debounce_ms = 300; if (const char* v = std::getenv("VA_VSM_DEBOUNCE_MS")) { try { int t = std::stoi(v); if (t>=0) debounce_ms = t; } catch (...) {} }
                vsm::v1::WatchStateReply rep;
                bool had_data = false;
                while (!vsm_watch_stop_.load() && reader->Read(&rep)) {
                    had_data = true;
                    std::unordered_map<std::string, Item> cur;
                    cur.reserve(static_cast<size_t>(rep.items_size()));
                    for (const auto& it : rep.items()) {
                        Item item{it.source_uri(), it.profile(), it.model_id()};
                        cur[it.attach_id()] = item;
                    }
                    // create/update
                    for (const auto& kv : cur) {
                        const std::string& sid = kv.first; const Item& item = kv.second;
                        const std::string prof = item.profile.empty()? default_profile : item.profile;
                        // find existing pipeline
                        bool exists = false; std::string exist_uri; std::string exist_model;
                        for (const auto& pinfo : track_manager_->listPipelines()) {
                            if (pinfo.stream_id == sid && pinfo.profile_id == prof) {
                                exists = true; exist_uri = pinfo.source_uri; exist_model = pinfo.model_id; break;
                            }
                        }
                        long long nowts = now_ms();
                        auto too_soon = [&](const std::string& key){ auto it=last_change_ms.find(key); return it!=last_change_ms.end() && (nowts - it->second) < debounce_ms; };
                        auto mark = [&](const std::string& key){ last_change_ms[key]=nowts; };

                        if (!exists) {
                            if (!too_soon(sid+":"+prof)) {
                                auto key = subscribeStream(sid, prof, item.uri);
                                if (key) {
                                    VA_LOG_INFO() << "[ControlPlane] auto-subscribe created key=" << *key << " stream=" << sid << " profile=" << prof;
                                    va::core::GlobalMetrics::cp_auto_subscribe_total.fetch_add(1);
                                } else {
                                    VA_LOG_WARN() << "[ControlPlane] auto-subscribe failed stream=" << sid << " err=" << last_error_;
                                    va::core::GlobalMetrics::cp_auto_subscribe_failed_total.fetch_add(1);
                                }
                                mark(sid+":"+prof);
                            }
                        } else {
                            // exists: if uri changed, switch source
                            if (!exist_uri.empty() && exist_uri != item.uri) {
                                if (!too_soon(std::string("sw:")+sid+":"+prof)) {
                                    bool ok = switchSource(sid, prof, item.uri);
                                    if (ok) { VA_LOG_INFO() << "[ControlPlane] auto-switchSource stream=" << sid << " profile=" << prof; va::core::GlobalMetrics::cp_auto_switch_source_total.fetch_add(1);} 
                                    else { VA_LOG_WARN() << "[ControlPlane] auto-switchSource failed stream=" << sid << " err=" << last_error_; va::core::GlobalMetrics::cp_auto_switch_source_failed_total.fetch_add(1);} 
                                    mark(std::string("sw:")+sid+":"+prof);
                                }
                            }
                            // exists: if model changed and provided, switch model
                            if (!item.model.empty() && exist_model != item.model) {
                                if (!too_soon(std::string("md:")+sid+":"+prof)) {
                                    bool okm = switchModel(sid, prof, item.model);
                                    if (okm) {
                                        VA_LOG_INFO() << "[ControlPlane] auto-switchModel stream=" << sid << " profile=" << prof << " model=" << item.model;
                                        va::core::GlobalMetrics::cp_auto_switch_model_total.fetch_add(1);
                                        mark(std::string("md:")+sid+":"+prof);
                                    } else {
                                        VA_LOG_WARN() << "[ControlPlane] auto-switchModel failed stream=" << sid << " model=" << item.model << " err=" << last_error_;
                                        va::core::GlobalMetrics::cp_auto_switch_model_failed_total.fetch_add(1);
                                        // 不标记md:去抖键，允许下一次WatchState重试
                                    }
                                }
                            }
                        }
                    }
                    // remove
                    long long nowts2 = now_ms();
                    auto too_soon2 = [&](const std::string& key){ auto it=last_change_ms.find(key); return it!=last_change_ms.end() && (nowts2 - it->second) < debounce_ms; };
                    auto mark2 = [&](const std::string& key){ last_change_ms[key]=nowts2; };
                    for (const auto& kv : last) {
                        if (cur.find(kv.first) == cur.end()) {
                            const std::string prof = kv.second.profile.empty()? default_profile : kv.second.profile;
                            if (!too_soon2(std::string("rm:")+kv.first+":"+prof)) {
                                unsubscribeStream(kv.first, prof);
                                VA_LOG_INFO() << "[ControlPlane] auto-unsubscribe stream=" << kv.first << " profile=" << prof;
                                va::core::GlobalMetrics::cp_auto_unsubscribe_total.fetch_add(1);
                                mark2(std::string("rm:")+kv.first+":"+prof);
                            }
                        }
                    }
                    last.swap(cur);
                }
                // reset backoff on activity; else apply backoff with jitter
                static int backoff_ms = app_config_.control_plane.backoff_start_ms; backoff_ms = env_int("VA_VSM_BACKOFF_MS_START", backoff_ms);
                static int backoff_max = app_config_.control_plane.backoff_max_ms; backoff_max = env_int("VA_VSM_BACKOFF_MS_MAX", backoff_max);
                static double jitter = app_config_.control_plane.backoff_jitter; if(const char* j=getenv("VA_VSM_BACKOFF_JITTER")) { try { jitter = std::stod(j);} catch(...){} }
                if (!had_data) {
                    int delay = backoff_ms;
                    // jitter +/-
                    int jspan = static_cast<int>(delay * jitter);
                    if (jspan > 0) {
                        auto seed = static_cast<unsigned>(now_ms());
                        int delta = (seed % (2*jspan+1)) - jspan; // [-jspan, +jspan]
                        delay = std::max(0, delay + delta);
                    }
                    std::this_thread::sleep_for(std::chrono::milliseconds(delay));
                    backoff_ms = std::min(backoff_ms * 2, backoff_max);
                } else {
                    backoff_ms = env_int("VA_VSM_BACKOFF_MS_START", 500);
                }
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "[ControlPlane] VSM watch exception: " << ex.what();
                // keep same backoff path as above when exceptions occur
                static int backoff_ms = app_config_.control_plane.backoff_start_ms; static int backoff_max = app_config_.control_plane.backoff_max_ms; static double jitter = app_config_.control_plane.backoff_jitter;
                int jspan = static_cast<int>(backoff_ms * jitter);
                int delay = backoff_ms + ((jspan>0)? ((int)(std::chrono::steady_clock::now().time_since_epoch().count()) % (2*jspan+1)) - jspan : 0);
                std::this_thread::sleep_for(std::chrono::milliseconds(std::max(0, delay)));
                backoff_ms = std::min(backoff_ms * 2, backoff_max);
            }
        }
        VA_LOG_INFO() << "[ControlPlane] VSM watch stopped";
    });
}
#endif

va::core::TrackManager* Application::trackManager() {
    return track_manager_.get();
}

std::vector<va::core::TrackManager::PipelineInfo> Application::pipelines() const {
    if (!track_manager_) {
        return {};
    }
    return track_manager_->listPipelines();
}

Application::SystemStats Application::systemStats() const {
    SystemStats stats;
    for (const auto& info : pipelines()) {
        stats.total_pipelines++;
        if (info.running) {
            stats.running_pipelines++;
        }
        stats.aggregate_fps += info.metrics.fps;
        stats.processed_frames += info.metrics.processed_frames;
        stats.dropped_frames += info.metrics.dropped_frames;
        stats.transport_packets += info.transport_stats.packets;
        stats.transport_bytes += info.transport_stats.bytes;
    }
    return stats;
}

bool Application::ffmpegEnabled() const {
#ifdef USE_FFMPEG
    return true;
#else
    return false;
#endif
}

bool Application::loadModel(const std::string& model_id) {
    auto model_opt = findModelById(model_id);
    if (!model_opt) {
        last_error_ = "model not found";
        return false;
    }

    active_models_by_task_[model_opt->task] = model_opt->id;

    if (!track_manager_) {
        last_error_.clear();
        return true;
    }

    bool success = true;
    for (const auto& info : track_manager_->listPipelines()) {
        if (info.task == model_opt->task) {
            if (!track_manager_->switchModel(info.stream_id, info.profile_id, model_opt->id)) {
                success = false;
                last_error_ = "failed to switch running pipeline";
            }
        }
    }
    if (success) {
        last_error_.clear();
    }
    return success;
}

bool Application::isModelActive(const std::string& model_id) const {
    auto it = detection_model_index_.find(model_id);
    if (it == detection_model_index_.end()) {
        return false;
    }
    auto active_it = active_models_by_task_.find(it->second.task);
    return active_it != active_models_by_task_.end() && active_it->second == model_id;
}

std::optional<std::string> Application::subscribeStream(const std::string& stream_id,
                                                        const std::string& profile_name,
                                                        const std::string& source_uri,
                                                        const std::optional<std::string>& model_override) {
    if (!initialized_ || !track_manager_) {
        last_error_ = "application not initialized";
        return std::nullopt;
    }

    auto profile_it = profile_index_.find(profile_name);
    if (profile_it == profile_index_.end()) {
        VA_LOG_WARN() << "[Application] subscribeStream failed: profile not found " << profile_name;
        last_error_ = "profile not found";
        return std::nullopt;
    }

    std::optional<DetectionModelEntry> model_opt;
    if (model_override && !model_override->empty()) {
        model_opt = findModelById(*model_override);
        if (!model_opt) {
            VA_LOG_WARN() << "[Application] subscribeStream failed: model override not found " << *model_override;
            last_error_ = "model not found";
            return std::nullopt;
        }
    } else {
        auto active_it = active_models_by_task_.find(profile_it->second.task);
        if (active_it != active_models_by_task_.end()) {
            model_opt = findModelById(active_it->second);
        }
        if (!model_opt) {
            model_opt = resolveModel(profile_it->second);
        }
        if (!model_opt) {
            VA_LOG_WARN() << "[Application] subscribeStream failed: no model resolved for task " << profile_it->second.task;
            last_error_ = "no model resolved for task";
            return std::nullopt;
        }
    }

    auto params_opt = resolveParams(profile_it->second.task);
    if (!params_opt) {
        params_opt = AnalyzerParamsEntry{};
    }

    va::core::SourceConfig source_cfg = buildSourceConfig(stream_id, source_uri);
    va::core::FilterConfig filter_cfg = buildFilterConfig(stream_id, profile_it->second, *model_opt, *params_opt);
    va::core::EncoderConfig encoder_cfg = buildEncoderConfig(profile_it->second);
    va::core::TransportConfig transport_cfg = buildTransportConfig(stream_id, profile_it->second);

    auto key = track_manager_->subscribe(source_cfg, filter_cfg, encoder_cfg, transport_cfg);
    if (key.empty()) {
        VA_LOG_WARN() << "[Application] subscribeStream failed: pipeline builder returned empty key for stream "
                  << stream_id << " profile " << profile_name << std::endl;
        if (filter_cfg.model_path.empty()) {
            last_error_ = "pipeline initialization failed";
        } else {
            last_error_ = "failed to initialize pipeline for model";
        }
        return std::nullopt;
    }
    last_error_.clear();
    return key;
}

bool Application::unsubscribeStream(const std::string& stream_id, const std::string& profile_name) {
    if (!initialized_ || !track_manager_) {
        return false;
    }
    track_manager_->unsubscribe(stream_id, profile_name);
    return true;
}

bool Application::switchSource(const std::string& stream_id,
                               const std::string& profile_name,
                               const std::string& new_uri) {
    if (!initialized_ || !track_manager_) {
        last_error_ = "application not initialized";
        return false;
    }
    if (!track_manager_->switchSource(stream_id, profile_name, new_uri)) {
        last_error_ = "failed to switch source";
        return false;
    }
    last_error_.clear();
    return true;
}

bool Application::switchModel(const std::string& stream_id,
                              const std::string& profile_name,
                              const std::string& model_id) {
    if (!initialized_ || !track_manager_) {
        last_error_ = "application not initialized";
        return false;
    }

    if (model_id.empty()) {
        last_error_ = "model id is empty";
        return false;
    }

    auto model_opt = findModelById(model_id);
    if (!model_opt) {
        last_error_ = "model not found";
        return false;
    }

    if (!track_manager_->switchModel(stream_id, profile_name, model_opt->id)) {
        last_error_ = "failed to switch model";
        return false;
    }

    last_error_.clear();
    return true;
}

bool Application::switchTask(const std::string& stream_id,
                             const std::string& profile_name,
                             const std::string& task_id) {
    if (!initialized_ || !track_manager_) {
        last_error_ = "application not initialized";
        return false;
    }

    if (!track_manager_->switchTask(stream_id, profile_name, task_id)) {
        last_error_ = "failed to switch task";
        return false;
    }

    last_error_.clear();
    return true;
}

bool Application::updateParams(const std::string& stream_id,
                               const std::string& profile_name,
                               const va::analyzer::AnalyzerParams& params) {
    if (!initialized_ || !track_manager_) {
        last_error_ = "application not initialized";
        return false;
    }

    auto shared_params = std::make_shared<va::analyzer::AnalyzerParams>(params);
    if (!track_manager_->setParams(stream_id, profile_name, std::move(shared_params))) {
        last_error_ = "failed to update analyzer params";
        return false;
    }

    last_error_.clear();
    return true;
}

bool Application::setEngine(const va::core::EngineDescriptor& descriptor) {
    if (!engine_manager_.setEngine(descriptor)) {
        last_error_ = "failed to set engine";
        return false;
    }
    last_error_.clear();
    return true;
}

va::core::EngineRuntimeStatus Application::engineRuntimeStatus() const {
    return engine_manager_.currentRuntimeStatus();
}

std::optional<DetectionModelEntry> Application::findModelById(const std::string& model_id) const {
    auto it = detection_model_index_.find(model_id);
    if (it != detection_model_index_.end()) {
        return it->second;
    }
    return std::nullopt;
}

std::optional<DetectionModelEntry> Application::resolveModel(const ProfileEntry& profile) const {
    if (!profile.model_id.empty()) {
        auto it = detection_model_index_.find(profile.model_id);
        if (it != detection_model_index_.end()) {
            return it->second;
        }
    }

    if (!profile.model_family.empty()) {
        std::string candidate = profile.task + ":" + profile.model_family;
        if (!profile.model_variant.empty()) {
            candidate += ":" + profile.model_variant;
        }
        auto it = detection_model_index_.find(candidate);
        if (it != detection_model_index_.end()) {
            return it->second;
        }
    }

    if (!profile.model_path.empty()) {
        DetectionModelEntry entry;
        entry.id = !profile.model_id.empty() ? profile.model_id : profile.model_path;
        entry.task = profile.task;
        entry.family = profile.model_family;
        entry.variant = profile.model_variant;
        entry.path = profile.model_path;
        entry.input_width = profile.input_width;
        entry.input_height = profile.input_height;
        return entry;
    }

    return std::nullopt;
}

std::optional<AnalyzerParamsEntry> Application::resolveParams(const std::string& task) const {
    std::string key = task;
    std::transform(key.begin(), key.end(), key.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
    auto it = analyzer_params_.find(key);
    if (it != analyzer_params_.end()) {
        return it->second;
    }
    return std::nullopt;
}

va::core::SourceConfig Application::buildSourceConfig(const std::string& stream_id,
                                                     const std::string& uri) const {
    va::core::SourceConfig cfg;
    cfg.stream_id = stream_id;
    cfg.uri = uri;
    return cfg;
}

va::core::FilterConfig Application::buildFilterConfig(const std::string& stream_id,
                                                     const ProfileEntry& profile,
                                                     const DetectionModelEntry& model,
                                                     const AnalyzerParamsEntry& params) const {
    va::core::FilterConfig cfg;
    cfg.profile_id = profile.name;
    cfg.task = profile.task;
    cfg.model_id = model.id;
    cfg.model_path = !model.path.empty() ? model.path : profile.model_path;

    cfg.input_width = profile.input_width > 0 ? profile.input_width : model.input_width;
    cfg.input_height = profile.input_height > 0 ? profile.input_height : model.input_height;

    cfg.confidence_threshold = model.conf > 0.0f ? model.conf : params.conf;
    cfg.iou_threshold = model.iou > 0.0f ? model.iou : params.iou;

    auto engine = engine_manager_.currentEngine();
    cfg.engine_type = engine.name;
    cfg.engine_provider = engine.provider;
    cfg.device_index = engine.device_index;

    auto toLower = [](std::string value) {
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        return value;
    };

    auto getBoolOption = [&](const std::string& key, bool fallback) {
        auto it = engine.options.find(key);
        if (it == engine.options.end()) {
            return fallback;
        }
        std::string value = it->second;
        std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) { return static_cast<char>(std::tolower(c)); });
        if (value == "1" || value == "true" || value == "yes" || value == "on") return true;
        if (value == "0" || value == "false" || value == "no" || value == "off") return false;
        return fallback;
    };

    auto getIntOption = [&](const std::string& key, int fallback) {
        auto it = engine.options.find(key);
        if (it == engine.options.end()) {
            return fallback;
        }
        try {
            return std::stoi(it->second);
        } catch (...) {
            return fallback;
        }
    };

    auto getSizeOption = [&](const std::string& key, std::size_t fallback) {
        auto it = engine.options.find(key);
        if (it == engine.options.end()) {
            return fallback;
        }
        try {
            long long v = std::stoll(it->second);
            if (v < 0) return fallback;
            return static_cast<std::size_t>(v);
        } catch (...) {
            return fallback;
        }
    };

    cfg.use_io_binding = getBoolOption("use_io_binding", cfg.use_io_binding);
    cfg.prefer_pinned_memory = getBoolOption("prefer_pinned_memory", cfg.prefer_pinned_memory);
    cfg.allow_cpu_fallback = getBoolOption("allow_cpu_fallback", cfg.allow_cpu_fallback);
    cfg.enable_profiling = getBoolOption("enable_profiling", cfg.enable_profiling);
    cfg.tensorrt_fp16 = getBoolOption("trt_fp16", cfg.tensorrt_fp16);
    cfg.tensorrt_int8 = getBoolOption("trt_int8", cfg.tensorrt_int8);
    cfg.tensorrt_workspace_mb = getIntOption("trt_workspace_mb", cfg.tensorrt_workspace_mb);
    cfg.tensorrt_max_partition_iterations = getIntOption("trt_max_partition_iterations", cfg.tensorrt_max_partition_iterations);
    cfg.tensorrt_min_subgraph_size = getIntOption("trt_min_subgraph_size", cfg.tensorrt_min_subgraph_size);
    cfg.io_binding_input_bytes = getSizeOption("io_binding_input_bytes", cfg.io_binding_input_bytes);
    cfg.io_binding_output_bytes = getSizeOption("io_binding_output_bytes", cfg.io_binding_output_bytes);
    // Map optional IoBinding staging options to filter config (carried into Ort options later)
    if (getBoolOption("stage_device_outputs", false)) {
        // Piggyback via engine.options; Ort session reads directly from cfg below
    }

    if (cfg.input_width == 0) {
        cfg.input_width = 640;
    }
    if (cfg.input_height == 0) {
        cfg.input_height = 640;
    }

    (void)stream_id; // reserved for future customization
    return cfg;
}

va::core::EncoderConfig Application::buildEncoderConfig(const ProfileEntry& profile) const {
    va::core::EncoderConfig cfg;
    cfg.width = profile.enc_width;
    cfg.height = profile.enc_height;
    cfg.fps = profile.enc_fps;
    cfg.bitrate_kbps = profile.enc_bitrate_kbps;
    cfg.gop = profile.enc_gop;
    cfg.bframes = profile.enc_bframes;
    cfg.preset = profile.enc_preset;
    cfg.tune = profile.enc_tune;
    cfg.profile = profile.enc_profile;
    std::string codec = profile.enc_codec;
    if (codec.empty()) {
        codec = "jpeg";
    }
    cfg.codec = codec;
    cfg.zero_latency = profile.enc_zero_latency;
    return cfg;
}

va::core::TransportConfig Application::buildTransportConfig(const std::string& stream_id,
                                                            const ProfileEntry& profile) const {
    va::core::TransportConfig cfg;
    cfg.whip_url = expandTemplate(profile.publish_whip_template, stream_id);
    return cfg;
}

std::string Application::expandTemplate(const std::string& templ,
                                        const std::string& stream_id) const {
    std::string result = templ;
    auto replace_all = [](std::string& target, const std::string& from, const std::string& to) {
        size_t pos = 0;
        while ((pos = target.find(from, pos)) != std::string::npos) {
            target.replace(pos, from.length(), to);
            pos += to.length();
        }
    };

    replace_all(result, "${stream}", stream_id);
    replace_all(result, "${whip_base}", app_config_.sfu_whip_base);
    replace_all(result, "${whep_base}", app_config_.sfu_whep_base);
    return result;
}

} // namespace va::app


