#pragma once

#include <chrono>
#include <cstddef>
#include <mutex>
#include <optional>
#include <string>
#include <unordered_map>
#include <vector>
#include <array>
#include <atomic>

// 轻量骨架：ModelRegistry（LRU+idle TTL 预留）。
// 当前版本仅记录模型元数据与最近访问时间；不持有实际推理会话。
// 通过 VA_MODEL_REGISTRY_ENABLED=1 启用，VA_MODEL_REGISTRY_CAP=64，VA_MODEL_IDLE_TTL_SEC=300 配置。

// 前置声明（来自 ConfigLoader.hpp）
struct DetectionModelEntry;

namespace va::analyzer {

struct ModelMeta {
  std::string id;
  std::string task;
  std::string path;
  std::string provider; // ort-cpu/ort-cuda/ort-trt
  int device {0};
  std::chrono::system_clock::time_point last_used{};
};

class ModelRegistry {
public:
  static ModelRegistry& instance();

  void configureFromEnv();
  void configurePreheatFromEnv();
  void setEnabled(bool on);
  bool enabled() const;

  void setCapacity(std::size_t cap);
  void setIdleTtlSeconds(int sec);

  void setModels(const std::vector<DetectionModelEntry>& models);

  // 记录一次模型使用（用于 idle TTL/LRU）
  void touch(const std::string& model_id);

  // 预热名单（骨架）：当前仅记录名单
  void schedulePreheat(const std::vector<std::string>& model_ids);

  // 启动后台预热线程（幂等，仅在 enabled 且列表非空时运行）
  void startPreheat();

  // 对外状态查询（用于 /api/system/info）
  bool preheatEnabled() const;
  int preheatConcurrency() const;
  std::vector<std::string> preheatList() const;
  std::string preheatStatus() const; // idle|running|done
  int warmedCount() const;
  // Cache config getters (for /system/info)
  std::size_t capacity() const;
  int idleTtlSeconds() const;

  struct MetricsSnapshot {
    bool enabled{false};
    int concurrency{0};
    int warmed{0};
    // cache stats
    std::size_t cache_entries{0};
    std::uint64_t cache_new_total{0};
    std::uint64_t cache_touch_total{0};
    std::uint64_t cache_evict_total{0};
    // histogram bounds (seconds)
    std::vector<double> bounds;
    std::vector<std::uint64_t> bucket_counts; // same size as bounds
    double duration_sum{0.0};
    std::uint64_t duration_count{0};
    std::uint64_t failed_total{0};
  };
  MetricsSnapshot metricsSnapshot() const;

private:
  ModelRegistry() = default;
  void pruneIdleLocked();
  void runPreheat();

  mutable std::mutex mu_;
  bool enabled_{false};
  std::size_t capacity_{64};
  int idle_ttl_sec_{300};
  std::unordered_map<std::string, ModelMeta> entries_; // key=model_id
  std::vector<std::string> preheat_list_;

  // preheat config/state
  bool preheat_enabled_{false};
  int preheat_concurrency_{2};
  int warmed_{0};
  enum class PreheatStatus { Idle, Running, Done };
  PreheatStatus preheat_status_{PreheatStatus::Idle};
  bool preheat_thread_spawned_{false};

  // Metrics for preheat
  std::array<double, 6> hist_bounds_{ {0.05, 0.1, 0.25, 0.5, 1.0, 2.0} };
  std::array<std::atomic<std::uint64_t>, 6> hist_counts_{};
  std::atomic<long long> hist_sum_us_{0};
  std::atomic<std::uint64_t> hist_count_{0};
  std::atomic<std::uint64_t> failed_total_{0};
  // Cache metrics
  std::atomic<std::uint64_t> cache_new_total_{0};
  std::atomic<std::uint64_t> cache_touch_total_{0};
  std::atomic<std::uint64_t> cache_evict_total_{0};
};

} // namespace va::analyzer
