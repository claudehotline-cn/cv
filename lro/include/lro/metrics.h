#pragma once
#include <string>
#include <vector>
#include <cstdint>

namespace lro {

struct ReasonCount { std::string reason; std::uint64_t count{0}; };

struct PhaseHistogram {
  std::vector<double> bounds;               // seconds
  std::vector<std::uint64_t> bucket_counts; // same size as bounds
  double        sum_seconds{0.0};
  std::uint64_t count{0};
};

struct LroMetricsDetail {
  // Overall
  std::size_t queue_length{0};
  std::size_t in_progress{0};
  std::size_t completed_ready_total{0};
  std::size_t completed_failed_total{0};
  std::size_t completed_cancelled_total{0};
  // Phase histograms
  PhaseHistogram opening; PhaseHistogram loading; PhaseHistogram starting;
  // Failed reasons (low cardinality)
  std::vector<ReasonCount> failed_by_reason;
  // Slots and backpressure estimate
  int open_rtsp_slots{0}, load_model_slots{0}, start_pipeline_slots{0};
  int retry_after_seconds{1};
  // Merge/fair scheduling
  std::uint64_t merge_non_terminal{0}, merge_ready{0}, merge_miss{0};
  std::uint64_t rr_rotations_total{0};
  // SSE
  int sse_subscriptions{0}, sse_sources{0}, sse_logs{0}, sse_events{0};
  std::uint64_t sse_reconnects_total{0};
};

} // namespace lro

