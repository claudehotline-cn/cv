#include "controlplane/metrics.hpp"
#include <sstream>

namespace controlplane::metrics {

static std::mutex g_mu;
static std::unordered_map<Key, unsigned long long, KeyHash> g_counts;
static std::atomic<long long> g_sse_conns{0};
static std::atomic<unsigned long long> g_sse_reconnects{0};

size_t KeyHash::operator()(const Key& k) const noexcept {
  std::hash<std::string> h;
  return (h(k.route) ^ (h(k.method) << 1)) ^ (std::hash<int>{}(k.code) << 2);
}

void inc_request(const std::string& route, const std::string& method, int code) {
  std::lock_guard<std::mutex> lk(g_mu);
  g_counts[Key{route,method,code}]++;
}

std::string render_prometheus() {
  std::ostringstream os;
  os << "# HELP cp_feature_enabled Feature toggle enabled (1/0)\n";
  os << "# TYPE cp_feature_enabled gauge\n";
  os << "cp_feature_enabled{feature=\"controlplane\"} 1\n";
  os << "# HELP cp_sse_connections Active SSE connections\n";
  os << "# TYPE cp_sse_connections gauge\n";
  os << "cp_sse_connections " << g_sse_conns.load() << "\n";
  os << "# HELP cp_sse_reconnects Total SSE connections opened\n";
  os << "# TYPE cp_sse_reconnects counter\n";
  os << "cp_sse_reconnects " << g_sse_reconnects.load() << "\n";
  os << "# HELP cp_request_total Total HTTP requests\n";
  os << "# TYPE cp_request_total counter\n";
  {
    std::lock_guard<std::mutex> lk(g_mu);
    for (const auto& kv : g_counts) {
      const auto& k = kv.first; auto v = kv.second;
      os << "cp_request_total{route=\"" << k.route << "\",method=\"" << k.method << "\",code=\"" << k.code << "\"} " << v << "\n";
    }
  }
  return os.str();
}

void sse_on_open() {
  g_sse_conns.fetch_add(1, std::memory_order_relaxed);
  g_sse_reconnects.fetch_add(1, std::memory_order_relaxed);
}
void sse_on_close() {
  g_sse_conns.fetch_sub(1, std::memory_order_relaxed);
}

} // namespace controlplane::metrics

