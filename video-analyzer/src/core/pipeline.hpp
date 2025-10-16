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
    const ZeroCopyMetrics& zerocopyMetrics() const { return zc_metrics_; }

    struct LatencySnapshot {
        static constexpr int kNumBuckets = 10; // ms buckets: 1,2,5,10,20,50,100,200,500,1000
        uint64_t buckets[kNumBuckets] {};
        uint64_t sum_us {0};
        uint64_t count {0};
    };
    LatencySnapshot latencyHist() const;

    struct StageLatencySnapshot {
        LatencySnapshot preproc;
        LatencySnapshot infer;
        LatencySnapshot postproc;
        LatencySnapshot encode;
    };
    StageLatencySnapshot stageLatency() const;

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
    ZeroCopyMetrics zc_metrics_;

    // Per-pipeline latency histogram (fixed buckets in ms)
    struct LatencyHist {
        static constexpr int kNumBuckets = 10;
        static constexpr double bounds_ms[kNumBuckets] = {1,2,5,10,20,50,100,200,500,1000};
        std::atomic<uint64_t> buckets[kNumBuckets];
        std::atomic<uint64_t> sum_us; // sum of latencies in microseconds
        std::atomic<uint64_t> count;
        LatencyHist() : sum_us(0), count(0) {
            for (int i=0;i<kNumBuckets;++i) buckets[i].store(0);
        }
        void add(double latency_ms) {
            // bucket index
            int idx = 0;
            while (idx < kNumBuckets && latency_ms > bounds_ms[idx]) ++idx;
            if (idx >= kNumBuckets) idx = kNumBuckets - 1;
            buckets[idx].fetch_add(1, std::memory_order_relaxed);
            // convert to microseconds to avoid double atomics
            uint64_t us = (latency_ms <= 0.0) ? 0ull : static_cast<uint64_t>(latency_ms * 1000.0);
            sum_us.fetch_add(us, std::memory_order_relaxed);
            count.fetch_add(1, std::memory_order_relaxed);
        }
        void snapshot(LatencySnapshot& out) const {
            for (int i=0;i<kNumBuckets;++i) out.buckets[i] = buckets[i].load(std::memory_order_relaxed);
            out.sum_us = sum_us.load(std::memory_order_relaxed);
            out.count = count.load(std::memory_order_relaxed);
        }
    };
    LatencyHist latency_hist_;

    // Stage-wise latency histograms
    LatencyHist preproc_hist_;
    LatencyHist infer_hist_;
    LatencyHist postproc_hist_;
    LatencyHist encode_hist_;

    // Latency sink to be attached to frames for stage recording
    class StageLatencySinkImpl : public va::core::Frame::LatencyMetricsSink {
    public:
        explicit StageLatencySinkImpl(Pipeline* p) : p_(p) {}
        void record_preproc_ms(double ms) override { if (p_) p_->preproc_hist_.add(ms); }
        void record_infer_ms(double ms) override { if (p_) p_->infer_hist_.add(ms); }
        void record_postproc_ms(double ms) override { if (p_) p_->postproc_hist_.add(ms); }
        void record_encode_ms(double ms) override { if (p_) p_->encode_hist_.add(ms); }
    private:
        Pipeline* p_ {nullptr};
    };
    StageLatencySinkImpl latency_sink_ {this};
};

} // namespace va::core
