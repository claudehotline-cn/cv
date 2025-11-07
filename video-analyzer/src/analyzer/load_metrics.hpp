#pragma once

#include <atomic>
#include <vector>
#include <cstddef>

namespace va { namespace analyzer { namespace metrics {

struct HistSnapshot {
  std::vector<double> bounds;           // upper bounds in seconds
  std::vector<unsigned long long> bucket_counts; // cumulative not required; exporter will accumulate
  unsigned long long count {0};
  double sum_seconds {0.0};
  unsigned long long failed_total {0};
};

// Record model session load duration (seconds). ok=false increments failure counter.
void record_model_session_load(double seconds, bool ok);
HistSnapshot snapshot_model_session_load();

// Record graph open_all background duration (seconds). ok=false increments failure counter.
void record_graph_open_duration(double seconds, bool ok);
HistSnapshot snapshot_graph_open_duration();

} } } // namespace

