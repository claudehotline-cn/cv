#pragma once

#include "core/pipeline_builder.hpp"
#include "media/transport.hpp"

#include <memory>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::analyzer {
struct AnalyzerParams;
}

namespace va::core {

class TrackManager {
public:
    explicit TrackManager(PipelineBuilder& builder);
    ~TrackManager();

    std::string subscribe(const SourceConfig& source_cfg,
                          const FilterConfig& filter_cfg,
                          const EncoderConfig& encoder_cfg,
                          const TransportConfig& transport_cfg);

    void unsubscribe(const std::string& stream_id, const std::string& profile_id);
    void reapIdle(int idle_timeout_ms);

    bool switchSource(const std::string& stream_id, const std::string& profile_id, const std::string& new_uri);
    bool switchModel(const std::string& stream_id, const std::string& profile_id, const std::string& new_model_id);
    bool switchTask(const std::string& stream_id, const std::string& profile_id, const std::string& task);
    bool setParams(const std::string& stream_id,
                   const std::string& profile_id,
                   std::shared_ptr<va::analyzer::AnalyzerParams> params);

    // Toggle per-pipeline analysis (true=analyze+overlay, false=raw passthrough)
    bool setAnalysisEnabled(const std::string& stream_id,
                            const std::string& profile_id,
                            bool enabled);

    struct PipelineInfo {
        std::string key;
        std::string stream_id;
        std::string profile_id;
        std::string source_uri;
        std::string model_id;
        std::string task;
        bool running {false};
        double last_active_ms {0.0};
        std::string track_id;
        va::core::Pipeline::Metrics metrics;
        va::media::ITransport::Stats transport_stats;
        EncoderConfig encoder_cfg;
        ZeroCopyMetrics zc;
        va::core::Pipeline::StageLatencySnapshot stage_latency;
        std::string decoder_label;
    };

    std::vector<PipelineInfo> listPipelines() const;

private:
    struct PipelineEntry {
        std::shared_ptr<Pipeline> pipeline;
        double last_active_ms {0.0};
        std::string stream_id;
        std::string profile_id;
        std::string source_uri;
        std::string model_id;
        std::string task;
        EncoderConfig encoder_cfg;
        std::string decoder_label;
    };

    std::string makeKey(const std::string& stream_id, const std::string& profile_id) const;

    PipelineBuilder& builder_;
    std::unordered_map<std::string, PipelineEntry> pipelines_;
    mutable std::mutex mutex_;
};

} // namespace va::core
