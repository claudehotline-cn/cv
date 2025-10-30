#pragma once

#include <unordered_map>
#include <thread>
#include <mutex>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_EXEC_HAS_CUDA 1
#    else
#      define VA_EXEC_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_EXEC_HAS_CUDA 1
#  endif
#else
#  define VA_EXEC_HAS_CUDA 0
   typedef void* cudaStream_t;
#endif

namespace va { namespace exec {

class StreamPool {
public:
    static StreamPool& instance() {
        static StreamPool pool;
        return pool;
    }

    cudaStream_t tls() {
#if VA_EXEC_HAS_CUDA
        std::lock_guard<std::mutex> lk(mu_);
        // Use a single global non-blocking stream to avoid cross-thread TLS mismatches
        if (!global_) {
            (void)cudaStreamCreateWithFlags(&global_, cudaStreamNonBlocking);
        }
        return global_;
#else
        return nullptr;
#endif
    }

private:
    StreamPool() = default;
    ~StreamPool() = default;
    StreamPool(const StreamPool&) = delete;
    StreamPool& operator=(const StreamPool&) = delete;

    std::mutex mu_;
    cudaStream_t global_ { nullptr };
};

} } // namespace va::exec

