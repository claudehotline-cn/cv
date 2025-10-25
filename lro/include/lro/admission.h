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
private:
  mutable std::mutex mu_;
  std::unordered_map<std::string,int> buckets_;
  int fair_window_{8};
};

} // namespace lro

