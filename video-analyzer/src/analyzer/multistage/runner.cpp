#include "analyzer/multistage/runner.hpp"

#include "exec/stream_pool.hpp"
#include "core/logger.hpp"
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
    // Use the global unified stream from StreamPool to ensure cross-stage consistency
    ctx_.stream = reinterpret_cast<void*>(va::exec::StreamPool::instance().tls());
    // One-shot diagnostic: print unified stream pointer to verify end-to-end binding
    static bool printed = false;
    if (!printed) {
        printed = true;
        VA_LOG_INFO() << "[StreamDiag] unified cudaStream=" << ctx_.stream;
    }
    #endif
}

AnalyzerMultistageAdapter::~AnalyzerMultistageAdapter() {
    // Ensure nodes are closed with the correct context
    graph_.close_all(ctx_);
#if VA_MS_HAS_CUDA_RUNTIME
    // Do not destroy the global stream; it's owned by StreamPool
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
