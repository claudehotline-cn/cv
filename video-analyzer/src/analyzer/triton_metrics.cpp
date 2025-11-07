#include "analyzer/triton_metrics.hpp"
#include "analyzer/load_metrics.hpp"

namespace va { namespace analyzer { namespace metrics {

// 直接复用 load_metrics 的 Hist 实现接口（以相同边界导出）
static HistSnapshot g_dummy; // placeholder for linkage

// 内部复用一套 histogram（参照 load_metrics 实现）
namespace {
struct Hist {
  static constexpr double bounds[11] = {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};
  std::atomic<unsigned long long> bucket[11]{};
  std::atomic<unsigned long long> count{0};
  std::atomic<long long> sum_us{0};
  std::atomic<unsigned long long> failed{0};
  void add(double sec, bool ok){
    if (!ok) failed.fetch_add(1, std::memory_order_relaxed);
    if (sec < 0) sec = 0;
    size_t idx=0; while (idx<11 && sec>bounds[idx]) ++idx; if (idx>=11) idx=10;
    bucket[idx].fetch_add(1, std::memory_order_relaxed);
    count.fetch_add(1, std::memory_order_relaxed);
    sum_us.fetch_add(static_cast<long long>(sec*1e6), std::memory_order_relaxed);
  }
  HistSnapshot snap() const;
};

HistSnapshot Hist::snap() const {
  HistSnapshot s;
  s.bounds = {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};
  s.bucket_counts.resize(11);
  for (size_t i=0;i<11;++i) s.bucket_counts[i] = bucket[i].load(std::memory_order_relaxed);
  s.count = count.load(std::memory_order_relaxed);
  s.sum_seconds = static_cast<double>(sum_us.load(std::memory_order_relaxed))/1e6;
  s.failed_total = failed.load(std::memory_order_relaxed);
  return s;
}

Hist& hist(){ static Hist h; return h; }
}

void triton_record_rpc(double seconds, bool ok, const char*) { hist().add(seconds, ok); }
HistSnapshot triton_snapshot_rpc() { return hist().snap(); }

} } }

