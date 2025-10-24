#pragma once
#include <string>
#include <functional>
#include <vector>
#include <cstdint>
#include <memory>

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
};

struct LroMetrics {
  size_t queue_length{0};
  size_t in_progress{0};
  // Optional: histograms, reasons, fairness/merge counters, slots, backpressure estimate, etc.
};

class Runner {
public:
  explicit Runner(const RunnerConfig& cfg) : cfg_(cfg) {}
  void addStep(const Step& s) { steps_.push_back(s); }

  // Wire admission buckets from outside (e.g., open_rtsp/load_model/start_pipeline)
  void bindBucket(const std::string& /*name*/, void* /*counting_semaphore*/ ) {}

  // Create/Get/Cancel minimal API (skeleton)
  std::string create(const std::string& /*spec_json*/, const std::string& /*base_key*/, bool /*prefer_reuse_ready*/){ return {}; }
  Operation get(const std::string& /*id*/) const { return {}; }
  bool cancel(const std::string& /*id*/) { return true; }

  // Watch stream (hook for SSE/WS). on_event should be invoked on status changes.
  void watch(const std::string& /*id*/, std::function<void(const Operation&)> /*on_event*/) {}

  LroMetrics metricsSnapshot() const { return {}; }

private:
  RunnerConfig cfg_{};
  std::vector<Step> steps_{};
};

} // namespace lro

