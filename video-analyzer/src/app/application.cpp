#include "app/application.hpp"

#include "ConfigLoader.hpp"
#include "analyzer/analyzer.hpp"
#include "core/logger.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"
#include "core/nvdec_events.hpp"

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
    engine_manager_.setEngine(std::move(descriptor));

    va::server::RestServerOptions rest_options;
    rest_options.host = "0.0.0.0";
    rest_options.port = 8082;
    rest_server_ = std::make_unique<va::server::RestServer>(rest_options, *this);

    initialized_ = true;
    return true;
}

bool Application::start() {
    if (!initialized_) {
        return false;
    }

    if (rest_server_) {
        return rest_server_->start();
    }
    return false;
}

void Application::shutdown() {
    if (!initialized_) {
        return;
    }

    if (rest_server_) {
        rest_server_->stop();
        rest_server_.reset();
    }

    track_manager_.reset();
    pipeline_builder_.reset();

    initialized_ = false;
}

bool Application::isInitialized() const {
    return initialized_;
}

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


