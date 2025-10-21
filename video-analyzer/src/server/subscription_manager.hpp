#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <string>
#include <thread>
#include <unordered_map>
#include <vector>
#include <array>

namespace va::app {
class Application;
}

namespace va::server {

enum class SubscriptionPhase {
    Pending,
    Preparing,
    OpeningRtsp,
    LoadingModel,
    StartingPipeline,
    Ready,
    Failed,
    Cancelled
};

struct SubscriptionRequest {
    std::string stream_id;
    std::string profile_id;
    std::string source_uri;
    std::optional<std::string> model_id;
};

struct SubscriptionState {
    std::atomic<SubscriptionPhase> phase{SubscriptionPhase::Pending};
    std::string reason;
    SubscriptionRequest request;
    std::string pipeline_key;
    std::string whep_url;
    std::atomic<bool> cancel{false};
    std::chrono::system_clock::time_point created_at{};
    std::atomic<bool> metrics_recorded{false};
};

class SubscriptionManager {
public:
    explicit SubscriptionManager(va::app::Application& app);
    ~SubscriptionManager();

    std::string enqueue(const SubscriptionRequest& request, bool prefer_reuse_ready = false);
    std::shared_ptr<SubscriptionState> get(const std::string& id) const;
    bool cancel(const std::string& id);
    void setWhepBase(std::string whep_base_url);
    void setMaxQueue(size_t n);
    void setHeavySlots(int n);
    size_t maxQueue() const;
    int heavySlots() const;

    struct MetricsSnapshot {
        size_t queue_length{0};
        size_t in_progress{0};
        size_t pending{0};
        size_t preparing{0};
        size_t opening{0};
        size_t loading{0};
        size_t starting{0};
        size_t ready{0};
        size_t failed{0};
        size_t cancelled{0};
        uint64_t completed_ready_total{0};
        uint64_t completed_failed_total{0};
        uint64_t completed_cancelled_total{0};
        // histogram buckets for total duration (s)
        std::vector<double> bounds;
        std::vector<uint64_t> bucket_counts; // same size as bounds
        double duration_sum{0.0};
        uint64_t duration_count{0};
    };
    MetricsSnapshot metricsSnapshot() const;

private:
    using StatePtr = std::shared_ptr<SubscriptionState>;

    struct Task {
        std::string id;
        StatePtr state;
    };
    struct HeavySlotGuard {
        SubscriptionManager* mgr;
        bool active;
        HeavySlotGuard(SubscriptionManager* m, bool a) : mgr(m), active(a) {}
        ~HeavySlotGuard() {
            if (mgr && active) mgr->releaseHeavySlot();
        }
    };

    void workerLoop();
    bool acquireHeavySlot();
    void releaseHeavySlot();
    void runSubscriptionTask(const std::string& id, const StatePtr& state);
    bool ensurePipelineStopped(const std::string& stream_id, const std::string& profile_id);
    std::string nextId();
    void recordCompletion(const StatePtr& state, SubscriptionPhase phase);

    mutable std::mutex mutex_;
    std::unordered_map<std::string, StatePtr> states_;
    std::unordered_map<std::string, std::string> key_index_;
    std::queue<Task> pending_;
    mutable std::condition_variable tasks_cv_;
    std::vector<std::thread> workers_;
    bool stop_{false};

    va::app::Application& app_;
    std::string whep_base_;

    mutable std::mutex heavy_mu_;
    std::condition_variable heavy_cv_;
    int heavy_slots_{2};
    int heavy_in_use_{0};

    // Metrics
    std::array<double, 6> hist_bounds_{ {0.5, 1.0, 2.0, 5.0, 10.0, 30.0} };
    std::array<std::atomic<uint64_t>, 6> hist_counts_ { };
    std::atomic<long long> hist_sum_us_{0};
    std::atomic<uint64_t> hist_count_{0};
    std::atomic<uint64_t> completed_ready_total_{0};
    std::atomic<uint64_t> completed_failed_total_{0};
    std::atomic<uint64_t> completed_cancelled_total_{0};

    // 简单队列上限，防止过载（可后续改为从配置加载）
    size_t max_queue_{1024};
}; 

const char* toString(SubscriptionPhase phase);

} // namespace va::server
