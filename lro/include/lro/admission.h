#pragma once
#include <string>
#include <unordered_map>
#include <mutex>

namespace lro {

// Skeleton admission policy (buckets + fair window config placeholder)
class AdmissionPolicy {
public:
  void setBucketCapacity(const std::string& name, int capacity) {
    std::lock_guard<std::mutex> lk(mu_); buckets_[name] = capacity; }
  int getBucketCapacity(const std::string& name) const {
    std::lock_guard<std::mutex> lk(mu_); auto it=buckets_.find(name); return it==buckets_.end()?0:it->second; }
  void setFairWindow(int n) { fair_window_ = n; }
  int fairWindow() const { return fair_window_; }
  // Generic Retry-After estimator: given queue length and effective worker slots,
  // return a conservative retry window in seconds [1, 60].
  int estimateRetryAfterSeconds(std::size_t queue_length, int effective_slots) const {
    if (effective_slots <= 0) effective_slots = 1;
    int est = 1;
    if (queue_length > 0) {
      const double wait = static_cast<double>(queue_length) / static_cast<double>(effective_slots);
      est = static_cast<int>(std::ceil(wait));
    }
    if (est < 1) est = 1; if (est > 60) est = 60; return est;
  }
private:
  mutable std::mutex mu_;
  std::unordered_map<std::string,int> buckets_;
  int fair_window_{8};
};

} // namespace lro
