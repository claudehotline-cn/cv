#pragma once
#include <string>
#include <unordered_map>
#include <mutex>
#include <optional>
#include <chrono>

namespace controlplane::cache {

struct Entry { std::string value; long long ts_ms{0}; };

class SimpleCache {
 public:
  static SimpleCache& instance();
  // Get cached json if not expired (ttl_ms). Returns true when hit.
  bool get(const std::string& key, long long ttl_ms, std::string* out);
  void put(const std::string& key, const std::string& val);
 private:
  static long long now_ms();
  std::mutex mu_;
  std::unordered_map<std::string, Entry> m_;
};

} // namespace controlplane::cache


