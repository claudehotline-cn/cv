#include "analyzer/load_metrics.hpp"

#include <mutex>
#include <algorithm>
#include <array>

namespace va { namespace analyzer { namespace metrics {

namespace {
struct Hist {
  // Fixed bounds in seconds
  static constexpr std::array<double, 11> kBounds {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};
  std::atomic<unsigned long long> buckets[kBounds.size()]{};
  std::atomic<unsigned long long> count{0};
  std::atomic<long long> sum_us{0};
  std::atomic<unsigned long long> failed{0};
  void add(double sec, bool ok) {
    if (!ok) failed.fetch_add(1, std::memory_order_relaxed);
    // clamp negatives to 0
    if (sec < 0) sec = 0;
    // bucket
    size_t idx = 0;
    while (idx < kBounds.size() && sec > kBounds[idx]) ++idx;
    if (idx >= kBounds.size()) idx = kBounds.size()-1;
    buckets[idx].fetch_add(1, std::memory_order_relaxed);
    count.fetch_add(1, std::memory_order_relaxed);
    long long us = static_cast<long long>(sec * 1e6);
    sum_us.fetch_add(us, std::memory_order_relaxed);
  }
  HistSnapshot snap() const {
    HistSnapshot s; s.bounds.assign(kBounds.begin(), kBounds.end());
    s.bucket_counts.resize(kBounds.size());
    for (size_t i=0;i<kBounds.size();++i) s.bucket_counts[i] = buckets[i].load(std::memory_order_relaxed);
    s.count = count.load(std::memory_order_relaxed);
    s.sum_seconds = static_cast<double>(sum_us.load(std::memory_order_relaxed))/1e6;
    s.failed_total = failed.load(std::memory_order_relaxed);
    return s;
  }
};

Hist& model_hist() { static Hist h; return h; }
Hist& graph_hist() { static Hist h; return h; }
}

void record_model_session_load(double seconds, bool ok) { model_hist().add(seconds, ok); }
HistSnapshot snapshot_model_session_load() { return model_hist().snap(); }

void record_graph_open_duration(double seconds, bool ok) { graph_hist().add(seconds, ok); }
HistSnapshot snapshot_graph_open_duration() { return graph_hist().snap(); }

} } } // namespace

