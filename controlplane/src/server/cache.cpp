#include "controlplane/cache.hpp"

namespace controlplane::cache {

static long long now_ms_impl() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

SimpleCache& SimpleCache::instance() {
  static SimpleCache s; return s;
}

long long SimpleCache::now_ms() { return now_ms_impl(); }

bool SimpleCache::get(const std::string& key, long long ttl_ms, std::string* out) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = m_.find(key);
  if (it == m_.end()) return false;
  auto now = now_ms();
  if (now - it->second.ts_ms > ttl_ms) return false;
  if (out) *out = it->second.value;
  return true;
}

void SimpleCache::put(const std::string& key, const std::string& val) {
  std::lock_guard<std::mutex> lk(mu_);
  m_[key] = Entry{val, now_ms()};
}

} // namespace controlplane::cache


