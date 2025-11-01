#include "controlplane/metrics.hpp"
#include <sstream>
#include <vector>
#include <cmath>
#include <atomic>

namespace controlplane::metrics {

static std::mutex g_mu;
static std::unordered_map<Key, unsigned long long, KeyHash> g_counts;
static std::atomic<long long> g_sse_conns{0};
static std::atomic<unsigned long long> g_sse_reconnects{0};

struct RMKey { std::string route; std::string method; bool operator==(const RMKey& o) const noexcept { return route==o.route && method==o.method; } };
struct RMHash { size_t operator()(const RMKey& k) const noexcept { std::hash<std::string> h; return h(k.route) ^ (h(k.method)<<1); } };

// 固定桶（ms）：5,10,25,50,100,250,500,1000,2500,5000
static const double BUCKETS[] = {5,10,25,50,100,250,500,1000,2500,5000};
static constexpr size_t NB = sizeof(BUCKETS)/sizeof(BUCKETS[0]);
// 每路由/方法的桶计数
static std::unordered_map<RMKey, std::vector<unsigned long long>, RMHash> g_hist;
// sum/count
static std::unordered_map<RMKey, double, RMHash> g_sum;
static std::unordered_map<RMKey, unsigned long long, RMHash> g_cnt;

// 下游错误计数
struct BEKey { std::string svc; std::string op; int code; bool operator==(const BEKey& o) const noexcept { return code==o.code && svc==o.svc && op==o.op; } };
struct BEHash { size_t operator()(const BEKey& k) const noexcept { std::hash<std::string> h; return (h(k.svc) ^ (h(k.op)<<1)) ^ (std::hash<int>{}(k.code)<<2); } };
static std::unordered_map<BEKey, unsigned long long, BEHash> g_backend_errs;

size_t KeyHash::operator()(const Key& k) const noexcept {
  std::hash<std::string> h;
  return (h(k.route) ^ (h(k.method) << 1)) ^ (std::hash<int>{}(k.code) << 2);
}

void inc_request(const std::string& route, const std::string& method, int code) {
  std::lock_guard<std::mutex> lk(g_mu);
  g_counts[Key{route,method,code}]++;
}

void inc_request_with_ms(const std::string& route, const std::string& method, int code, double duration_ms) {
  {
    std::lock_guard<std::mutex> lk(g_mu);
    g_counts[Key{route,method,code}]++;
    RMKey k{route,method};
    auto& vec = g_hist[k];
    if (vec.empty()) vec.assign(NB, 0);
    // 记录到第一个>=duration的桶
    size_t idx = NB; for (size_t i=0;i<NB;i++){ if (duration_ms <= BUCKETS[i]) { idx=i; break; } }
    if (idx<NB) vec[idx]++;
    g_sum[k] += duration_ms;
    g_cnt[k]++;
  }
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
    // 直方图
    os << "# HELP cp_request_duration_ms Request duration in milliseconds\n";
    os << "# TYPE cp_request_duration_ms histogram\n";
    for (const auto& kv : g_hist) {
      const auto& k = kv.first; const auto& vec = kv.second;
      unsigned long long cumul = 0;
      for (size_t i=0;i<NB;i++) {
        cumul += vec[i];
        os << "cp_request_duration_ms_bucket{route=\""<<k.route<<"\",method=\""<<k.method<<"\",le=\""<< BUCKETS[i] <<"\"} "<< cumul <<"\n";
      }
      // +Inf bucket == total count
      unsigned long long total = g_cnt.at(k);
      os << "cp_request_duration_ms_bucket{route=\""<<k.route<<"\",method=\""<<k.method<<"\",le=\"+Inf\"} "<< total <<"\n";
      os << "cp_request_duration_ms_sum{route=\""<<k.route<<"\",method=\""<<k.method<<"\"} "<< g_sum.at(k) <<"\n";
      os << "cp_request_duration_ms_count{route=\""<<k.route<<"\",method=\""<<k.method<<"\"} "<< total <<"\n";
    }
    // 下游错误计数
    os << "# HELP cp_backend_errors_total gRPC backend error counts\n";
    os << "# TYPE cp_backend_errors_total counter\n";
    for (const auto& kv2 : g_backend_errs) {
      const auto& k = kv2.first; auto v = kv2.second;
      os << "cp_backend_errors_total{service=\""<<k.svc<<"\",method=\""<<k.op<<"\",code=\""<<k.code<<"\"} "<< v <<"\n";
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

void inc_backend_error(const std::string& service, int grpc_code) {
  std::lock_guard<std::mutex> lk(g_mu);
  g_backend_errs[BEKey{service, std::string("unknown"), grpc_code}]++;
}
void inc_backend_error(const std::string& service, const std::string& method, int grpc_code) {
  std::lock_guard<std::mutex> lk(g_mu);
  g_backend_errs[BEKey{service, method, grpc_code}]++;
}

} // namespace controlplane::metrics

