#pragma once

// Lightweight per-thread CUDA runtime initialization helpers.
// Route A: ensure each worker thread initializes CUDA context exactly once
// to prevent invalid device/context errors during zero-copy paths.

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_HAS_CUDA_RUNTIME 1
#    else
#      define VA_HAS_CUDA_RUNTIME 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_HAS_CUDA_RUNTIME 1
#  endif
#else
#  define VA_HAS_CUDA_RUNTIME 0
#endif

namespace va::core {

// Initialize CUDA on the calling thread if needed.
// If device_id < 0, attempt to use current device, otherwise fallback to 0.
inline void ensure_cuda_ready(int device_id = -1) {
#if VA_HAS_CUDA_RUNTIME
    static thread_local int tls_dev = -2; // -2 means uninitialized on this thread
    int target = device_id;
    if (target < 0) {
        int cur = -1;
        cudaError_t ge = cudaGetDevice(&cur);
        if (ge != cudaSuccess || cur < 0) {
            target = 0;
        } else {
            target = cur;
        }
    }
    if (tls_dev != target) {
        (void)cudaSetDevice(target);
        (void)cudaFree(0); // force runtime/context lazy init
        tls_dev = target;
    }
#else
    (void)device_id;
#endif
}

} // namespace va::core

