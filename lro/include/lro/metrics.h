// This header intentionally contains only generic sample types for users who
// want to build richer metrics on top of Runner. The LRO core does not depend
// on these types and does not assume any domain-specific phases or reasons.
#pragma once
#include <string>
#include <unordered_map>
#include <cstdint>

namespace lro {

struct ReasonCount { std::string reason; std::uint64_t count{0}; };

struct GenericHistogram {
  // Cumulative histogram representation
  std::vector<double> bounds;               // seconds
  std::vector<std::uint64_t> bucket_counts; // same size as bounds
  double        sum_seconds{0.0};
  std::uint64_t count{0};
};

struct MetricsSample {
  std::size_t queue_length{0};
  std::size_t in_progress{0};
  std::unordered_map<std::string, std::uint64_t> states; // phase -> count
  std::uint64_t completed_ready{0}, completed_failed{0}, completed_cancelled{0};
  GenericHistogram total_duration;
  std::vector<ReasonCount> failed_by_reason; // optional, user-populated
};

} // namespace lro
