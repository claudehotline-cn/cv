#include "analyzer/triton_metrics.hpp"

#include <atomic>
#include <cstring>

namespace va { namespace analyzer { namespace metrics {

namespace {
struct Hist {
  static constexpr double kBounds[11] = {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};
  std::atomic<unsigned long long> bucket[11]{};
  std::atomic<unsigned long long> count{0};
  std::atomic<long long> sum_us{0};
  void add(double sec){
    if (sec < 0) sec = 0;
    size_t idx=0; while (idx<11 && sec>kBounds[idx]) ++idx; if (idx>=11) idx=10;
    bucket[idx].fetch_add(1, std::memory_order_relaxed);
    count.fetch_add(1, std::memory_order_relaxed);
    sum_us.fetch_add(static_cast<long long>(sec*1e6), std::memory_order_relaxed);
  }
  void fill(TritonRpcSnapshot& out) const {
    out.bounds.assign(std::begin(kBounds), std::end(kBounds));
    out.bucket_counts.resize(11);
    for (size_t i=0;i<11;++i) out.bucket_counts[i] = bucket[i].load(std::memory_order_relaxed);
    out.count = count.load(std::memory_order_relaxed);
    out.sum_seconds = static_cast<double>(sum_us.load(std::memory_order_relaxed))/1e6;
  }
};

// Low-cardinality failure reasons (fixed slots to避免指标爆炸)
struct FailReasons {
  enum ReasonIdx { Create, InvalidInput, MkInput, MkOutput, Infer, NoOutput, Timeout, Unavailable, Other, kNumReasons };
  const char* names[kNumReasons] = {"create","invalid_input","mk_input","mk_output","infer","no_output","timeout","unavailable","other"};
  std::atomic<unsigned long long> ctr[kNumReasons]{};
  std::atomic<unsigned long long> total{0};
  ReasonIdx map(const char* r) const {
    if (!r || !*r) return Other;
    for (int i=0;i<(int)kNumReasons;++i) { if (std::strcmp(r, names[i])==0) return (ReasonIdx)i; }
    return Other;
  }
  void add(const char* r){ ctr[map(r)].fetch_add(1, std::memory_order_relaxed); total.fetch_add(1, std::memory_order_relaxed); }
  void fill(TritonRpcSnapshot& out) const {
    out.failed_total = total.load(std::memory_order_relaxed);
    out.failed_by_reason.clear(); out.failed_by_reason.reserve(kNumReasons);
    for (int i=0;i<(int)kNumReasons;++i) { FailItem f; f.reason = names[i]; f.value = ctr[i].load(std::memory_order_relaxed); out.failed_by_reason.push_back(f); }
  }
};

struct State {
  Hist hist;
  FailReasons reasons;
};

State& S(){ static State s; return s; }
}

void triton_record_rpc(double seconds, bool ok, const char* reason) {
  S().hist.add(seconds);
  if (!ok) S().reasons.add(reason);
}

TritonRpcSnapshot triton_snapshot_rpc() {
  TritonRpcSnapshot s{}; S().hist.fill(s); S().reasons.fill(s); return s;
}

} } }
