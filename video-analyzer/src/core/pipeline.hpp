#pragma once

#include "core/utils.hpp"
#include "media/transport.hpp"

#include <atomic>
#include <memory>
#include <mutex>
#include <thread>

namespace va::media {
class ISwitchableSource;
class IEncoder;
}

namespace va::analyzer {
class Analyzer;
}

namespace va::core {

class Pipeline {
public:
    Pipeline(std::shared_ptr<va::media::ISwitchableSource> source,
             std::shared_ptr<va::analyzer::Analyzer> analyzer,
             std::shared_ptr<va::media::IEncoder> encoder,
             std::shared_ptr<va::media::ITransport> transport,
             std::string stream_id,
             std::string profile_id);
    ~Pipeline();

    void start();
    void stop();
    bool isRunning() const;

    va::media::ISwitchableSource* source();
    va::analyzer::Analyzer* analyzer();
    const std::string& streamId() const { return stream_id_; }
    const std::string& profileId() const { return profile_id_; }

    struct Metrics {
        double fps {0.0};
        double avg_latency_ms {0.0};
        double last_processed_ms {0.0};
        uint64_t processed_frames {0};
        uint64_t dropped_frames {0};
    };

    Metrics metrics() const;
    void recordFrameProcessed(double latency_ms);
    void recordFrameDropped();
    va::media::ITransport::Stats transportStats() const;

private:
    void run();
    bool pullFrame(core::Frame& frame);
    bool processFrame(const core::Frame& in);

    std::shared_ptr<va::media::ISwitchableSource> source_;
    std::shared_ptr<va::analyzer::Analyzer> analyzer_;
    std::shared_ptr<va::media::IEncoder> encoder_;
    std::shared_ptr<va::media::ITransport> transport_;
    std::atomic<bool> running_ {false};
    std::thread worker_;
    std::mutex mutex_;
    std::string stream_id_;
    std::string profile_id_;
    std::string track_id_;

    std::atomic<uint64_t> processed_frames_ {0};
    std::atomic<uint64_t> dropped_frames_ {0};
    std::atomic<double> avg_latency_ms_ {0.0};
    std::atomic<double> fps_ {0.0};
    std::atomic<double> last_timestamp_ms_ {0.0};
};

} // namespace va::core
