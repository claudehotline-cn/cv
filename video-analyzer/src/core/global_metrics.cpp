#include "core/global_metrics.hpp"

namespace va::core::GlobalMetrics {

std::atomic<uint64_t> d2d_nv12_frames {0};
std::atomic<uint64_t> cpu_fallback_skips {0};
std::atomic<uint64_t> eagain_retry_count {0};
std::atomic<uint64_t> overlay_nv12_kernel_hits {0};
std::atomic<uint64_t> overlay_nv12_passthrough {0};
std::atomic<uint64_t> cp_auto_subscribe_total {0};
std::atomic<uint64_t> cp_auto_unsubscribe_total {0};
std::atomic<uint64_t> cp_auto_switch_source_total {0};
std::atomic<uint64_t> cp_auto_switch_model_total {0};
std::atomic<uint64_t> cp_auto_subscribe_failed_total {0};
std::atomic<uint64_t> cp_auto_switch_source_failed_total {0};
std::atomic<uint64_t> cp_auto_switch_model_failed_total {0};

} // namespace va::core::GlobalMetrics
