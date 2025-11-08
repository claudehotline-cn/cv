#pragma once

#include <vector>
#include <string>

namespace va { namespace analyzer { namespace metrics {

struct HistSnapshot;

struct FailItem { std::string reason; unsigned long long value {0}; };
struct TritonRpcSnapshot {
  // latency histogram
  std::vector<double> bounds;               // bucket upper bounds
  std::vector<unsigned long long> bucket_counts; // counts per bucket
  unsigned long long count {0};
  double sum_seconds {0.0};
  unsigned long long failed_total {0};
  std::vector<FailItem> failed_by_reason;   // low-cardinality reason stats
};

// Record a Triton RPC sample; reason is optional and should be from a small fixed set
// e.g. "create","invalid_input","mk_input","mk_output","infer","no_output","timeout","unavailable".
void triton_record_rpc(double seconds, bool ok, const char* reason = nullptr);
TritonRpcSnapshot triton_snapshot_rpc();

} } }
