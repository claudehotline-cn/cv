#pragma once
#include <string>
#include <functional>
#include <vector>
#include <cstdint>
#include <memory>
#include <optional>
#include <unordered_map>
#include <deque>
#include <mutex>
#include <thread>
#include <atomic>
#include <condition_variable>
#include <chrono>
#include <cstdio>

namespace lro {

struct Timeline {
  uint64_t ts_pending{0}, ts_preparing{0}, ts_opening{0}, ts_loading{0}, ts_starting{0}, ts_ready{0}, ts_failed{0}, ts_cancelled{0};
};

struct OperationStatus {
  std::string phase;      // pending/preparing/.../ready/failed/cancelled
  int progress{0};        // 0..100
  std::string reason;     // normalized reason
};

struct Operation {
  std::string id;
  std::string spec_json;
  OperationStatus status;
  Timeline timeline;
  std::string result_json;
};

enum class StepClass { IO, Heavy, Start };

struct Context { /* reserved for future (logger, env, metrics, ...) */ };

struct Step {
  std::string name;
  StepClass cls{StepClass::IO};
  std::string bucket_key; // admission bucket name
  bool cancelable{true};
  int timeout_ms{-1};
  std::function<void(Operation&, Context&)> fn; // may throw for failure
};

struct IStateStore; struct AdmissionPolicy; struct INotifier; struct IWalAdapter;

struct RunnerConfig {
  IStateStore* store{nullptr};
  AdmissionPolicy* admission{nullptr};
  INotifier* notifier{nullptr};
  int fair_window{8};
  std::function<int(int,int)> retry_estimator; // (queue_len, slots_min) -> seconds
  std::function<std::string(const std::string&, const std::string&)> normalizer; // (app_err, fallback)
  struct MergePolicy { std::function<std::string(const std::string&)> base_key_fn; bool prefer_reuse_ready{true}; } merge;
  IWalAdapter* wal{nullptr};
  // Minimal provider bridge into host application until native Steps are implemented
  struct Provider {
    // Create operation from spec, return id
    std::function<std::string(const std::string& spec_json,
                              const std::string& base_key,
                              bool prefer_reuse_ready)> create;
    // Cancel by id
    std::function<bool(const std::string& id)> cancel;
    // Fill Operation snapshot by id; return false when not found
    std::function<bool(const std::string& id, Operation& out)> get;
    // Optional: register watcher to push updates
    std::function<void(const std::string& id,
                       std::function<void(const Operation&)>)> watch;
  } provider;
};

struct LroMetrics {
  std::size_t queue_length{0};
  std::size_t in_progress{0};
  // States
  std::size_t pending{0}, preparing{0}, opening{0}, loading{0}, starting{0}, ready{0}, failed{0}, cancelled{0};
};

class Runner {
public:
  explicit Runner(const RunnerConfig& cfg) : cfg_(cfg) {}
  void addStep(const Step& s) { steps_.push_back(s); }

  // Wire admission buckets from outside (e.g., open_rtsp/load_model/start_pipeline)
  void bindBucket(const std::string& /*name*/, void* /*counting_semaphore*/ ) {}

  // Create/Get/Cancel minimal API
  std::string create(const std::string& spec_json, const std::string& base_key, bool prefer_reuse_ready){
    // Synchronously obtain canonical id from provider (bridge) to keep REST semantics
    std::string id;
    if (cfg_.provider.create) id = cfg_.provider.create(spec_json, base_key, prefer_reuse_ready);
    if (id.empty()) {
      // Fallback: generate ephemeral id (not ideal if provider absent)
      id = genId(base_key);
    }
    // Initialize operation record
    Operation op; op.id = id; op.spec_json = spec_json;
    op.status.phase = "pending"; op.status.progress = 0; op.status.reason.clear();
    op.timeline.ts_pending = now_ms();
    {
      std::lock_guard<std::mutex> lk(mu_);
      ops_[id] = op;
      q_.push_back(id);
    }
    cv_.notify_one();
    ensure_worker();
    // optional state store omitted in minimal runner
    notify(id);
    return id;
  }
  Operation get(const std::string& id) const {
    // Minimal runner stores in-memory
    std::lock_guard<std::mutex> lk(mu_);
    auto it = ops_.find(id);
    if (it != ops_.end()) return it->second;
    return Operation{}; // not found
  }
  bool cancel(const std::string& id) {
    bool ok = false;
    if (cfg_.provider.cancel) ok = cfg_.provider.cancel(id);
    std::lock_guard<std::mutex> lk(mu_);
    auto it = ops_.find(id);
    if (it != ops_.end()) {
      auto& op = it->second;
      if (op.status.phase != "ready" && op.status.phase != "failed" && op.status.phase != "cancelled") {
        op.status.phase = "cancelled";
        op.timeline.ts_cancelled = now_ms();
      }
      ok = true; // best-effort
    }
    notify(id);
    return ok;
  }

  // Watch stream (hook for SSE/WS). on_event should be invoked on status changes.
  void watch(const std::string& id, std::function<void(const Operation&)> on_event) {
    // Register local watcher; emit current snapshot once
    {
      std::lock_guard<std::mutex> lk(mu_);
      watchers_[id].push_back(on_event);
    }
    on_event(get(id));
    // Optionally, also attach to provider's watch to propagate terminal events
    if (cfg_.provider.watch) { cfg_.provider.watch(id, std::move(on_event)); }
  }

  LroMetrics metricsSnapshot() const {
    LroMetrics m;
    std::lock_guard<std::mutex> lk(mu_);
    m.queue_length = q_.size();
    for (const auto& kv : ops_) {
      const auto& ph = kv.second.status.phase;
      if (ph != "ready" && ph != "failed" && ph != "cancelled") m.in_progress++;
      if (ph == "pending") m.pending++;
      else if (ph == "preparing") m.preparing++;
      else if (ph == "opening_rtsp") m.opening++;
      else if (ph == "loading_model") m.loading++;
      else if (ph == "starting_pipeline") m.starting++;
      else if (ph == "ready") m.ready++;
      else if (ph == "failed") m.failed++;
      else if (ph == "cancelled") m.cancelled++;
    }
    return m;
  }

private:
  RunnerConfig cfg_{};
  std::vector<Step> steps_{};
  mutable std::mutex mu_;
  std::unordered_map<std::string, Operation> ops_;
  std::unordered_map<std::string, std::vector<std::function<void(const Operation&)>>> watchers_;
  std::deque<std::string> q_;
  std::condition_variable cv_;
  std::atomic<bool> stop_{false};
  std::thread worker_;

  static std::uint64_t now_ms() {
    using namespace std::chrono;
    return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
  }
  static std::string genId(const std::string& base_key){
    // Simple hex-suffix id
    static std::atomic<std::uint64_t> s{1};
    std::uint64_t v = s.fetch_add(1);
    char buf[32];
    snprintf(buf, sizeof(buf), "%s-%llx", base_key.c_str(), static_cast<unsigned long long>(v));
    return std::string(buf);
  }
  void ensure_worker() {
    if (worker_.joinable()) return;
    worker_ = std::thread([this]{ this->run(); });
  }
  void run() {
    while (!stop_.load(std::memory_order_relaxed)) {
      std::string id;
      {
        std::unique_lock<std::mutex> lk(mu_);
        if (q_.empty()) {
          cv_.wait_for(lk, std::chrono::milliseconds(200));
          if (q_.empty()) continue;
        }
        id = q_.front(); q_.pop_front();
      }
      // Advance phases quickly to starting (best-effort timeline)
      auto bump = [&](const char* phase, std::uint64_t* ts){
        std::lock_guard<std::mutex> lk(mu_);
        auto it = ops_.find(id);
        if (it == ops_.end()) return;
        auto& op = it->second;
        if (std::string(phase) == op.status.phase) return;
        op.status.phase = phase; if (ts) *ts = now_ms();
        notify_nolock(id, op);
      };
      {
        std::lock_guard<std::mutex> lk(mu_);
        auto it = ops_.find(id);
        if (it == ops_.end()) continue;
        // pending -> preparing
      }
      bump("preparing", nullptr); { std::lock_guard<std::mutex> lk(mu_); auto& op=ops_[id]; op.timeline.ts_preparing = now_ms(); } notify(id);
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      bump("opening_rtsp", nullptr); { std::lock_guard<std::mutex> lk(mu_); auto& op=ops_[id]; op.timeline.ts_opening = now_ms(); } notify(id);
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      bump("loading_model", nullptr); { std::lock_guard<std::mutex> lk(mu_); auto& op=ops_[id]; op.timeline.ts_loading = now_ms(); } notify(id);
      std::this_thread::sleep_for(std::chrono::milliseconds(10));
      bump("starting_pipeline", nullptr); { std::lock_guard<std::mutex> lk(mu_); auto& op=ops_[id]; op.timeline.ts_starting = now_ms(); } notify(id);
      // Do not mark ready/failed here; rely on underlying provider and REST GET fallback
    }
  }
  void notify(const std::string& id) {
    Operation snap = get(id);
    std::lock_guard<std::mutex> lk(mu_);
    notify_nolock(id, snap);
  }
  void notify_nolock(const std::string& id, const Operation& snap) {
    auto it = watchers_.find(id);
    if (it == watchers_.end()) return;
    for (auto& cb : it->second) { try { cb(snap); } catch(...){} }
  }
};

} // namespace lro
