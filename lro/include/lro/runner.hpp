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

  // Create/Get/Cancel minimal API (provider-backed for now)
  std::string create(const std::string& spec_json, const std::string& base_key, bool prefer_reuse_ready){
    if (cfg_.provider.create) return cfg_.provider.create(spec_json, base_key, prefer_reuse_ready);
    return {};
  }
  Operation get(const std::string& id) const {
    Operation op; op.id = id; // id echo for caller convenience
    if (cfg_.provider.get) {
      Operation out;
      if (cfg_.provider.get(id, out)) return out;
      // not found -> empty id
      return Operation{};
    }
    return op;
  }
  bool cancel(const std::string& id) {
    if (cfg_.provider.cancel) return cfg_.provider.cancel(id);
    return false;
  }

  // Watch stream (hook for SSE/WS). on_event should be invoked on status changes.
  void watch(const std::string& id, std::function<void(const Operation&)> on_event) {
    if (cfg_.provider.watch) { cfg_.provider.watch(id, std::move(on_event)); }
  }

  LroMetrics metricsSnapshot() const { return {}; }

private:
  RunnerConfig cfg_{};
  std::vector<Step> steps_{};
};

} // namespace lro
