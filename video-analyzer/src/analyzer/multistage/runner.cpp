#include "analyzer/multistage/runner.hpp"

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_HAS_CUDA_RUNTIME 1
#    else
#      define VA_MS_HAS_CUDA_RUNTIME 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_HAS_CUDA_RUNTIME 1
#  endif
#else
#  define VA_MS_HAS_CUDA_RUNTIME 0
#endif

namespace va { namespace analyzer { namespace multistage {

AnalyzerMultistageAdapter::AnalyzerMultistageAdapter() {
#if VA_MS_HAS_CUDA_RUNTIME
    // Create a dedicated stream for this pipeline (best-effort)
    cudaStream_t s = nullptr;
    if (cudaStreamCreate(&s) == cudaSuccess) {
        ctx_.stream = reinterpret_cast<void*>(s);
    }
#endif
}

AnalyzerMultistageAdapter::~AnalyzerMultistageAdapter() {
    // Ensure nodes are closed with the correct context
    graph_.close_all(ctx_);
#if VA_MS_HAS_CUDA_RUNTIME
    if (ctx_.stream) {
        cudaStreamDestroy(reinterpret_cast<cudaStream_t>(ctx_.stream));
        ctx_.stream = nullptr;
    }
#endif
}

bool AnalyzerMultistageAdapter::process(const va::core::Frame& in, va::core::Frame& out) {
    Packet p; p.frame = in;
    if (!graph_.run(p, ctx_)) return false;
    out = p.frame;
    return true;
}

void AnalyzerMultistageAdapter::configurePools(std::size_t host_block_bytes, int host_capacity,
                                               std::size_t device_block_bytes, int device_capacity) {
    if (host_block_bytes > 0) {
        host_pool_ = std::make_unique<va::core::HostBufferPool>(host_block_bytes, host_capacity > 0 ? host_capacity : 8);
        ctx_.host_pool = host_pool_.get();
    }
    if (device_block_bytes > 0) {
        gpu_pool_ = std::make_unique<va::core::GpuBufferPool>(device_block_bytes, device_capacity > 0 ? device_capacity : 4);
        ctx_.gpu_pool = gpu_pool_.get();
    }
}

} } } // namespace
