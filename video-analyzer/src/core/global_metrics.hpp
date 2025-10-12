#pragma once

#include <atomic>
#include <cstdint>

namespace va::core::GlobalMetrics {

extern std::atomic<uint64_t> d2d_nv12_frames;          // NVENC device NV12 direct-feed frames
extern std::atomic<uint64_t> cpu_fallback_skips;       // Skipped CPU upload due to no BGR (device path active)
extern std::atomic<uint64_t> eagain_retry_count;       // Encoder EAGAIN drain+retry occurrences
extern std::atomic<uint64_t> overlay_nv12_kernel_hits; // NV12 kernel overlay executions (boxes>0)
extern std::atomic<uint64_t> overlay_nv12_passthrough; // NV12 passthrough (boxes==0)
// Control-plane (auto orchestration) metrics
extern std::atomic<uint64_t> cp_auto_subscribe_total;
extern std::atomic<uint64_t> cp_auto_unsubscribe_total;
extern std::atomic<uint64_t> cp_auto_switch_source_total;
extern std::atomic<uint64_t> cp_auto_switch_model_total;
extern std::atomic<uint64_t> cp_auto_subscribe_failed_total;
extern std::atomic<uint64_t> cp_auto_switch_source_failed_total;
extern std::atomic<uint64_t> cp_auto_switch_model_failed_total;

struct Snapshot {
    uint64_t d2d_nv12_frames;
    uint64_t cpu_fallback_skips;
    uint64_t eagain_retry_count;
    uint64_t overlay_nv12_kernel_hits;
    uint64_t overlay_nv12_passthrough;
    uint64_t cp_auto_subscribe_total;
    uint64_t cp_auto_unsubscribe_total;
    uint64_t cp_auto_switch_source_total;
    uint64_t cp_auto_switch_model_total;
    uint64_t cp_auto_subscribe_failed_total;
    uint64_t cp_auto_switch_source_failed_total;
    uint64_t cp_auto_switch_model_failed_total;
};

inline Snapshot snapshot() {
    return Snapshot{
        d2d_nv12_frames.load(),
        cpu_fallback_skips.load(),
        eagain_retry_count.load(),
        overlay_nv12_kernel_hits.load(),
        overlay_nv12_passthrough.load(),
        cp_auto_subscribe_total.load(),
        cp_auto_unsubscribe_total.load(),
        cp_auto_switch_source_total.load(),
        cp_auto_switch_model_total.load(),
        cp_auto_subscribe_failed_total.load(),
        cp_auto_switch_source_failed_total.load(),
        cp_auto_switch_model_failed_total.load()
    };
}

} // namespace va::core::GlobalMetrics
