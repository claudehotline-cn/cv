#pragma once
#include <string>
#include <unordered_map>
#include <mutex>
#include <memory>
#include <cmath>
#include "lro/retry_estimator.h"

namespace lro {

// Skeleton admission policy (buckets + fair window config placeholder)
class AdmissionPolicy {
public:
  struct Snapshot {
    std::unordered_map<std::string,int> capacities;
    int fair_window{0};
  };
  void setBucketCapacity(const std::string& name, int capacity) {
    std::lock_guard<std::mutex> lk(mu_); buckets_[name] = capacity; }
  int getBucketCapacity(const std::string& name) const {
    std::lock_guard<std::mutex> lk(mu_); auto it=buckets_.find(name); return it==buckets_.end()?0:it->second; }
  void setFairWindow(int n) { fair_window_ = n; }
  int fairWindow() const { return fair_window_; }
  Snapshot snapshot() const {
    std::lock_guard<std::mutex> lk(mu_);
    Snapshot s; s.capacities = buckets_; s.fair_window = fair_window_; return s;
  }
  void setRetryEstimator(std::shared_ptr<IRetryEstimator> est) { std::lock_guard<std::mutex> lk(mu_); estimator_ = std::move(est); }
  // Generic Retry-After estimator: given queue length and effective worker slots,
  // return a conservative retry window in seconds [1, 60].
  int estimateRetryAfterSeconds(std::size_t queue_length, int effective_slots) const {
    std::shared_ptr<IRetryEstimator> est;
    {
      std::lock_guard<std::mutex> lk(mu_);
      est = estimator_;
    }
    if (est) return est->estimate(queue_length, effective_slots);
    // fallback to simple logic
    if (effective_slots <= 0) effective_slots = 1;
    int v = 1; if (queue_length > 0) { const double w = static_cast<double>(queue_length) / static_cast<double>(effective_slots); v = static_cast<int>(std::ceil(w)); }
    if (v < 1) v = 1; if (v > 60) v = 60; return v;
  }
private:
  mutable std::mutex mu_;
  std::unordered_map<std::string,int> buckets_;
  int fair_window_{8};
  std::shared_ptr<IRetryEstimator> estimator_;
};

} // namespace lro
