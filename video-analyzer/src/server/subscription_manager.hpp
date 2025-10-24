#pragma once

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <memory>
#include <mutex>
#include <optional>
#include <queue>
#include <deque>
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
    // Optional: requester identity for quota/ACL tracking
    std::optional<std::string> requester_key;
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
    std::atomic<bool> db_recorded{false};
    // requester identity (for quotas)
    std::string requester_key;
    // 阶段时间线（ms since epoch），原子写一次读取多次，避免锁
    std::atomic<std::uint64_t> ts_pending{0};
    std::atomic<std::uint64_t> ts_preparing{0};
    std::atomic<std::uint64_t> ts_opening{0};
    std::atomic<std::uint64_t> ts_loading{0};
    std::atomic<std::uint64_t> ts_starting{0};
    std::atomic<std::uint64_t> ts_ready{0};
    std::atomic<std::uint64_t> ts_failed{0};
    std::atomic<std::uint64_t> ts_cancelled{0};
};

class SubscriptionManager {
public:
    explicit SubscriptionManager(va::app::Application& app);
    ~SubscriptionManager();

    // 默认幂等复用：同一 stream_id:profile_id 已 Ready 时直接复用现有订阅
    std::string enqueue(const SubscriptionRequest& request, bool prefer_reuse_ready = true);
    std::shared_ptr<SubscriptionState> get(const std::string& id) const;
    bool cancel(const std::string& id);
  void setWhepBase(std::string whep_base_url);
  void setMaxQueue(size_t n);
    void setHeavySlots(int n);
    void setModelSlots(int n);
    void setRtspSlots(int n);
    // 分阶段并发：可选（未设置则由服务器侧回退到 legacy 值）
    void setOpenRtspSlots(int n);
    void setStartPipelineSlots(int n);
    void setTtlSeconds(int n);
    size_t maxQueue() const;
    int heavySlots() const;
    int modelSlots() const;
    int rtspSlots() const;
    int openRtspSlots() const;
    int startPipelineSlots() const;
    int ttlSeconds() const;
    // Fairness/merge metrics getters
    uint64_t rrRotations() const;
    uint64_t mergeHitNonTerminal() const;
    uint64_t mergeHitReady() const;
    uint64_t mergeMiss() const;

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
        std::vector<std::pair<std::string, uint64_t>> failed_by_reason;
        // per-phase histograms (use same bounds)
        std::vector<uint64_t> opening_bucket_counts;
        std::vector<uint64_t> loading_bucket_counts;
        std::vector<uint64_t> starting_bucket_counts;
        double opening_duration_sum{0.0};
        uint64_t opening_duration_count{0};
        double loading_duration_sum{0.0};
        uint64_t loading_duration_count{0};
        double starting_duration_sum{0.0};
        uint64_t starting_duration_count{0};
    };
    MetricsSnapshot metricsSnapshot() const;
    // Count non-terminal states by requester_key (for quotas)
    int countInProgressByKey(const std::string& key) const;

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
  bool acquireModelSlot();
  void releaseModelSlot();
  bool acquireRtspSlot();
  void releaseRtspSlot();
  bool acquireOpenRtspSlot();
  void releaseOpenRtspSlot();
  bool acquireStartSlot();
  void releaseStartSlot();
  void runSubscriptionTask(const std::string& id, const StatePtr& state);
  bool ensurePipelineStopped(const std::string& stream_id, const std::string& profile_id);
  std::string nextId();
    void recordCompletion(const StatePtr& state, SubscriptionPhase phase);
    void cleanerLoop();
    static std::string normalizeReason(const std::string& app_err, const char* fallback);

    mutable std::mutex mutex_;
    std::unordered_map<std::string, StatePtr> states_;
    std::unordered_map<std::string, std::string> key_index_;
    std::deque<Task> pending_;
    mutable std::condition_variable tasks_cv_;
    std::vector<std::thread> workers_;
    bool stop_{false};
    std::thread cleaner_;
    std::atomic<bool> cleaner_stop_{false};

    va::app::Application& app_;
    std::string whep_base_;

    mutable std::mutex heavy_mu_;
  std::condition_variable heavy_cv_;
  int heavy_slots_{2};
  int heavy_in_use_{0};

  mutable std::mutex model_mu_;
  std::condition_variable model_cv_;
  int model_slots_{2};
  int model_in_use_{0};

  mutable std::mutex rtsp_mu_;
  std::condition_variable rtsp_cv_;
  int rtsp_slots_{4};
    int rtsp_in_use_{0};

  // Optional: per-phase slots
  mutable std::mutex open_mu_;
  std::condition_variable open_cv_;
  int open_rtsp_slots_{0};
  int open_in_use_{0};

  mutable std::mutex start_mu_;
  std::condition_variable start_cv_;
  int start_slots_{0};
  int start_in_use_{0};

    // Metrics
    std::array<double, 6> hist_bounds_{ {0.5, 1.0, 2.0, 5.0, 10.0, 30.0} };
    std::array<std::atomic<uint64_t>, 6> hist_counts_ { };
    std::atomic<long long> hist_sum_us_{0};
    std::atomic<uint64_t> hist_count_{0};
    // per-phase hist: opening_rtsp, loading_model, starting_pipeline
    std::array<std::atomic<uint64_t>, 6> hist_opening_counts_ { };
    std::array<std::atomic<uint64_t>, 6> hist_loading_counts_ { };
    std::array<std::atomic<uint64_t>, 6> hist_starting_counts_ { };
    std::atomic<long long> hist_opening_sum_us_{0};
    std::atomic<uint64_t> hist_opening_count_{0};
    std::atomic<long long> hist_loading_sum_us_{0};
    std::atomic<uint64_t> hist_loading_count_{0};
    std::atomic<long long> hist_starting_sum_us_{0};
    std::atomic<uint64_t> hist_starting_count_{0};
    std::atomic<uint64_t> completed_ready_total_{0};
    std::atomic<uint64_t> completed_failed_total_{0};
    std::atomic<uint64_t> completed_cancelled_total_{0};

    // Fair scheduling and merge metrics
    std::string last_served_key_;
    int fair_window_{8};
    std::atomic<uint64_t> rr_rotations_{0};
    std::atomic<uint64_t> merge_hit_non_terminal_{0};
    std::atomic<uint64_t> merge_hit_ready_{0};
    std::atomic<uint64_t> merge_miss_{0};

  // Metrics: failed reasons
  mutable std::mutex reasons_mu_;
    std::unordered_map<std::string, std::atomic<uint64_t>> failed_reasons_;

    // 简单队列上限，防止过载（可后续改为从配置加载）
    size_t max_queue_{1024};

    // 终态任务保留 TTL（秒），到期后清理（默认 15 分钟）
    int ttl_seconds_{900};
};

const char* toString(SubscriptionPhase phase);

} // namespace va::server
