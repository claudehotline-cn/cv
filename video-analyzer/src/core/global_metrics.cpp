#include "core/global_metrics.hpp"

namespace va::core::GlobalMetrics {

std::atomic<uint64_t> d2d_nv12_frames {0};
std::atomic<uint64_t> cpu_fallback_skips {0};
std::atomic<uint64_t> eagain_retry_count {0};
std::atomic<uint64_t> overlay_nv12_kernel_hits {0};
std::atomic<uint64_t> overlay_nv12_passthrough {0};

} // namespace va::core::GlobalMetrics

