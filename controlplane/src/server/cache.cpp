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
  if (it == m_.end()) { g_misses.fetch_add(1, std::memory_order_relaxed); return false; }
  auto now = now_ms();
  if (now - it->second.ts_ms > ttl_ms) { g_misses.fetch_add(1, std::memory_order_relaxed); return false; }
  if (out) *out = it->second.value;
  g_hits.fetch_add(1, std::memory_order_relaxed);
  return true;
}

void SimpleCache::put(const std::string& key, const std::string& val) {
  std::lock_guard<std::mutex> lk(mu_);
  m_[key] = Entry{val, now_ms()};
}

SimpleCache::Stats SimpleCache::stats() {
  return Stats{ g_hits.load(std::memory_order_relaxed), g_misses.load(std::memory_order_relaxed) };
}

} // namespace controlplane::cache


static std::atomic<unsigned long long> g_hits{0};
static std::atomic<unsigned long long> g_misses{0};
