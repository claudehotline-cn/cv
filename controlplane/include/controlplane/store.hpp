#pragma once
#include <string>
#include <unordered_map>
#include <mutex>
#include <optional>
#include <chrono>

namespace controlplane {

struct TimelineEvent {
  std::string phase;  // pending/ready/failed/cancelled/...
  long long ts_ms{0};
  std::string reason; // optional
};

struct SubscriptionRecord {
  std::string cp_id;
  std::string stream_id;
  std::string profile;
  std::string source_uri;
  std::string model_id;
  std::string va_subscription_id; // pipeline_key from VA
  TimelineEvent last;
  unsigned long long version{0};
};

class Store {
 public:
  static Store& instance();

  std::string create(const std::string& stream_id,
                     const std::string& profile,
                     const std::string& source_uri,
                     const std::string& model_id,
                     const std::string& va_subscription_id);

  std::optional<SubscriptionRecord> get(const std::string& cp_id);

  void set_phase(const std::string& cp_id, const std::string& phase, const std::string& reason = "");

  void erase(const std::string& cp_id);

  static std::string make_etag(const SubscriptionRecord& r); // W/"<version>"

 private:
  std::string gen_cp_id();
  static long long now_ms();

 private:
  std::mutex mu_;
  std::unordered_map<std::string, SubscriptionRecord> m_;
  unsigned long long seq_{0};
};

} // namespace controlplane


