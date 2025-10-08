#include "core/track_manager.hpp"

#include "analyzer/analyzer.hpp"
#include "media/source.hpp"
#include "media/source_ffmpeg_rtsp.hpp"
#if defined(USE_CUDA) && defined(WITH_NVDEC)
#include "media/source_nvdec_cuda.hpp"
#endif
#include "core/logger.hpp"
#include "core/drop_metrics.hpp"
#include "core/source_reconnects.hpp"
#include "core/nvdec_events.hpp"

#include <utility>
#include <vector>

namespace va::core {

TrackManager::TrackManager(PipelineBuilder& builder)
    : builder_(builder) {}

TrackManager::~TrackManager() {
    std::scoped_lock lock(mutex_);
    for (auto& [key, entry] : pipelines_) {
        if (entry.pipeline) {
            entry.pipeline->stop();
        }
    }
    pipelines_.clear();
}

std::string TrackManager::subscribe(const SourceConfig& source_cfg,
                                    const FilterConfig& filter_cfg,
                                    const EncoderConfig& encoder_cfg,
                                    const TransportConfig& transport_cfg) {
    auto pipeline = builder_.build(source_cfg, filter_cfg, encoder_cfg, transport_cfg);
    if (!pipeline) {
        return {};
    }

    pipeline->start();

    const std::string key = makeKey(source_cfg.stream_id, filter_cfg.profile_id);

    {
        std::scoped_lock lock(mutex_);
        PipelineEntry entry;
        entry.pipeline = std::move(pipeline);
        entry.last_active_ms = va::core::ms_now();
        entry.stream_id = source_cfg.stream_id;
        entry.profile_id = filter_cfg.profile_id;
        entry.source_uri = source_cfg.uri;
        entry.model_id = filter_cfg.model_id;
        entry.task = filter_cfg.task;
        entry.encoder_cfg = encoder_cfg;
        // Derive decoder label from concrete source type
        if (entry.pipeline && entry.pipeline->source()) {
#if defined(USE_CUDA) && defined(WITH_NVDEC)
            if (std::dynamic_pointer_cast<va::media::NvdecRtspSource>(std::shared_ptr<va::media::ISwitchableSource>(entry.pipeline->source(), [](auto*){}))) {
                entry.decoder_label = "nvdec";
            } else
#endif
            if (std::dynamic_pointer_cast<va::media::FfmpegRtspSource>(std::shared_ptr<va::media::ISwitchableSource>(entry.pipeline->source(), [](auto*){}))) {
                entry.decoder_label = "ffmpeg";
            } else {
                entry.decoder_label = "other";
            }
        }
        pipelines_[key] = std::move(entry);
    }

    return key;
}

void TrackManager::unsubscribe(const std::string& stream_id, const std::string& profile_id) {
    const std::string key = makeKey(stream_id, profile_id);
    std::shared_ptr<Pipeline> to_stop;
    {
        std::scoped_lock lock(mutex_);
        auto it = pipelines_.find(key);
        if (it != pipelines_.end()) {
            // keep a local strong ref; erase from map first to avoid re-entrancy while holding lock
            to_stop = it->second.pipeline;
            pipelines_.erase(it);
        }
    }
    if (to_stop) {
        try {
            to_stop->stop();
        } catch (const std::exception& ex) {
            VA_LOG_ERROR() << "[TrackManager] exception while stopping pipeline '" << key << "': " << ex.what();
        } catch (...) {
            VA_LOG_ERROR() << "[TrackManager] unknown exception while stopping pipeline '" << key << "'";
        }
    }
}

void TrackManager::reapIdle(int idle_timeout_ms) {
    const double now = va::core::ms_now();
    std::scoped_lock lock(mutex_);
    for (auto it = pipelines_.begin(); it != pipelines_.end();) {
        double last = it->second.last_active_ms;
        if (it->second.pipeline) {
            const auto metrics = it->second.pipeline->metrics();
            if (metrics.last_processed_ms > 0.0) {
                last = metrics.last_processed_ms;
            }
        }

        if ((now - last) > idle_timeout_ms) {
            it = pipelines_.erase(it);
        } else {
            ++it;
        }
    }
}

bool TrackManager::switchSource(const std::string& stream_id,
                                const std::string& profile_id,
                                const std::string& new_uri) {
    const std::string key = makeKey(stream_id, profile_id);
    std::scoped_lock lock(mutex_);
    auto it = pipelines_.find(key);
    if (it == pipelines_.end()) {
        return false;
    }
    try {
        va::core::DropMetrics::mapUriToSourceId(new_uri, stream_id);
    } catch (...) {
        // ignore metrics mapping errors
    }
    try {
        va::core::SourceReconnects::mapUriToSourceId(new_uri, stream_id);
    } catch (...) {}
    try {
        va::core::NvdecEvents::mapUriToSourceId(new_uri, stream_id);
    } catch (...) {}
    return it->second.pipeline->source()->switchUri(new_uri);
}

bool TrackManager::switchModel(const std::string& stream_id,
                               const std::string& profile_id,
                               const std::string& new_model_id) {
    const std::string key = makeKey(stream_id, profile_id);
    std::scoped_lock lock(mutex_);
    auto it = pipelines_.find(key);
    if (it == pipelines_.end()) {
        return false;
    }
    it->second.model_id = new_model_id;
    return it->second.pipeline->analyzer()->switchModel(new_model_id);
}

bool TrackManager::switchTask(const std::string& stream_id,
                              const std::string& profile_id,
                              const std::string& task) {
    const std::string key = makeKey(stream_id, profile_id);
    std::scoped_lock lock(mutex_);
    auto it = pipelines_.find(key);
    if (it == pipelines_.end()) {
        return false;
    }
    it->second.task = task;
    return it->second.pipeline->analyzer()->switchTask(task);
}

bool TrackManager::setParams(const std::string& stream_id,
                             const std::string& profile_id,
                             std::shared_ptr<va::analyzer::AnalyzerParams> params) {
    const std::string key = makeKey(stream_id, profile_id);
    std::scoped_lock lock(mutex_);
    auto it = pipelines_.find(key);
    if (it == pipelines_.end()) {
        return false;
    }
    return it->second.pipeline->analyzer()->updateParams(std::move(params));
}

std::string TrackManager::makeKey(const std::string& stream_id, const std::string& profile_id) const {
    return stream_id + ":" + profile_id;
}

std::vector<TrackManager::PipelineInfo> TrackManager::listPipelines() const {
    std::vector<PipelineInfo> infos;
    std::scoped_lock lock(mutex_);
    infos.reserve(pipelines_.size());
    for (const auto& [key, entry] : pipelines_) {
        PipelineInfo info;
        info.key = key;
        info.stream_id = entry.stream_id;
        info.profile_id = entry.profile_id;
        info.source_uri = entry.source_uri;
        info.model_id = entry.model_id;
        info.task = entry.task;
        info.running = entry.pipeline ? entry.pipeline->isRunning() : false;
        if (entry.pipeline) {
            info.metrics = entry.pipeline->metrics();
            info.last_active_ms = info.metrics.last_processed_ms > 0.0
                ? info.metrics.last_processed_ms
                : entry.last_active_ms;
            info.track_id = entry.pipeline->streamId() + ":" + entry.pipeline->profileId();
            info.transport_stats = entry.pipeline->transportStats();
            info.zc = entry.pipeline->zerocopyMetrics();
            info.stage_latency = entry.pipeline->stageLatency();
            info.decoder_label = entry.decoder_label;
        } else {
            info.last_active_ms = entry.last_active_ms;
        }
        info.encoder_cfg = entry.encoder_cfg;
        infos.emplace_back(std::move(info));
    }
    return infos;
}

} // namespace va::core
