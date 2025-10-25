#pragma once
#include <cstddef>

namespace lro {

// Retry estimator SPI: decouples admission capacity from wait-time estimation.
struct IRetryEstimator {
  virtual ~IRetryEstimator() = default;
  virtual int estimate(std::size_t queue_length, int effective_slots) const = 0; // seconds [1, 60]
};

// Default conservative estimator: ceil(queue/slots) clamped to [1, 60].
struct SimpleRetryEstimator : public IRetryEstimator {
  int estimate(std::size_t queue_length, int effective_slots) const override {
    if (effective_slots <= 0) effective_slots = 1;
    int est = 1;
    if (queue_length > 0) {
      const double wait = static_cast<double>(queue_length) / static_cast<double>(effective_slots);
      est = static_cast<int>(std::ceil(wait));
    }
    if (est < 1) est = 1; if (est > 60) est = 60; return est;
  }
};

} // namespace lro

