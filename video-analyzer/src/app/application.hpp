#pragma once

#include "composition_root.hpp"
#include "core/engine_manager.hpp"
#include "core/pipeline_builder.hpp"
#include "core/track_manager.hpp"
#include "server/rest.hpp"
#include "ConfigLoader.hpp"

#include <map>
#include <memory>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::analyzer {
struct AnalyzerParams;
}

namespace va { namespace control { class IGraphAdapter; class PipelineController; struct OpaquePtr; } }

namespace va::app {

class Application {
public:
    Application();
    ~Application();

    bool initialize(const std::string& config_dir);
    bool start();
    void shutdown();

    bool isInitialized() const;

    va::core::TrackManager* trackManager();

    const std::vector<DetectionModelEntry>& detectionModels() const { return detection_models_; }
    const std::vector<ProfileEntry>& profiles() const { return profiles_; }
    const std::map<std::string, AnalyzerParamsEntry>& analyzerParams() const { return analyzer_params_; }
    const AppConfigPayload& appConfig() const { return app_config_; }
    std::vector<va::core::TrackManager::PipelineInfo> pipelines() const;
    bool loadModel(const std::string& model_id);
    bool isModelActive(const std::string& model_id) const;
    struct SystemStats {
        size_t total_pipelines {0};
        size_t running_pipelines {0};
        double aggregate_fps {0.0};
        uint64_t processed_frames {0};
        uint64_t dropped_frames {0};
        uint64_t transport_packets {0};
        uint64_t transport_bytes {0};
    };
    SystemStats systemStats() const;
    bool ffmpegEnabled() const;

    std::optional<std::string> subscribeStream(const std::string& stream_id,
                                               const std::string& profile_name,
                                               const std::string& source_uri,
                                               const std::optional<std::string>& model_override = std::nullopt);
    bool unsubscribeStream(const std::string& stream_id, const std::string& profile_name);
    bool switchSource(const std::string& stream_id,
                      const std::string& profile_name,
                      const std::string& new_uri);
    bool switchModel(const std::string& stream_id,
                     const std::string& profile_name,
                     const std::string& model_id);
    bool switchTask(const std::string& stream_id,
                    const std::string& profile_name,
                    const std::string& task_id);
    bool updateParams(const std::string& stream_id,
                      const std::string& profile_name,
                      const va::analyzer::AnalyzerParams& params);
    bool setEngine(const va::core::EngineDescriptor& descriptor);
    const std::string& lastError() const { return last_error_; }

    va::core::EngineRuntimeStatus engineRuntimeStatus() const;
    va::core::EngineDescriptor currentEngine() const { return engine_manager_.currentEngine(); }

private:
    std::string config_dir_;
    va::core::EngineManager engine_manager_;
    va::core::Factories factories_;
    std::unique_ptr<va::core::PipelineBuilder> pipeline_builder_;
    std::unique_ptr<va::core::TrackManager> track_manager_;
    std::unique_ptr<va::server::RestServer> rest_server_;
    bool initialized_ {false};

    AppConfigPayload app_config_;
    std::vector<DetectionModelEntry> detection_models_;
    std::vector<ProfileEntry> profiles_;
    std::map<std::string, AnalyzerParamsEntry> analyzer_params_;

    std::unordered_map<std::string, DetectionModelEntry> detection_model_index_;
    std::unordered_map<std::string, ProfileEntry> profile_index_;
    std::unordered_map<std::string, std::string> active_models_by_task_;
    std::string last_error_;

    std::optional<DetectionModelEntry> resolveModel(const ProfileEntry& profile) const;
    std::optional<DetectionModelEntry> findModelById(const std::string& model_id) const;
    std::optional<AnalyzerParamsEntry> resolveParams(const std::string& task) const;
    va::core::SourceConfig buildSourceConfig(const std::string& stream_id,
                                            const std::string& uri) const;
    va::core::FilterConfig buildFilterConfig(const std::string& stream_id,
                                            const ProfileEntry& profile,
                                            const DetectionModelEntry& model,
                                            const AnalyzerParamsEntry& params) const;
    va::core::EncoderConfig buildEncoderConfig(const ProfileEntry& profile) const;
    va::core::TransportConfig buildTransportConfig(const std::string& stream_id,
                                                  const ProfileEntry& profile) const;
    std::string expandTemplate(const std::string& templ,
                               const std::string& stream_id) const;

#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
    // 控制平面（内嵌）
    std::unique_ptr<class va::control::IGraphAdapter> graph_adapter_;
    std::unique_ptr<class va::control::PipelineController> pipeline_controller_;
    class va::control::OpaquePtr grpc_server_;
#endif
};

} // namespace va::app

