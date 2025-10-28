#pragma once

#include <cstddef>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_UTILS_HAS_CUDA_RUNTIME 1
#    else
#      define VA_UTILS_HAS_CUDA_RUNTIME 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_UTILS_HAS_CUDA_RUNTIME 1
#  endif
#else
#  define VA_UTILS_HAS_CUDA_RUNTIME 0
#endif

namespace va { namespace utils {

inline void ensure_cuda_ready(int device_id) {
#if VA_UTILS_HAS_CUDA_RUNTIME
    // Bind thread to device and warm up primary context.
    cudaSetDevice(device_id);
    (void)cudaFree(0);
#else
    (void)device_id;
#endif
}

} } // namespace va::utils

