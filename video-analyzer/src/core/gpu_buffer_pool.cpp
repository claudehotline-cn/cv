#include "core/gpu_buffer_pool.hpp"

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

GpuBufferPool::GpuBufferPool(std::size_t block_bytes, std::size_t capacity)
    : block_bytes_(block_bytes), capacity_(capacity) {}

GpuBufferPool::~GpuBufferPool() {
#if VA_HAS_CUDA_RUNTIME
    for (auto& m : free_) {
        if (m.ptr) cudaFree(m.ptr);
    }
#endif
    free_.clear();
}

GpuBufferPool::Memory GpuBufferPool::acquire(std::size_t bytes) {
    Memory mem;
#if VA_HAS_CUDA_RUNTIME
    if (bytes == 0) return mem;
    if (block_bytes_ < bytes) {
        // reset pool sizing and free existing blocks
        for (auto& m : free_) { if (m.ptr) cudaFree(m.ptr); }
        free_.clear();
        block_bytes_ = bytes;
    }
    {
        std::lock_guard<std::mutex> lk(mutex_);
        if (!free_.empty()) {
            mem = free_.back();
            free_.pop_back();
        }
    }
    if (!mem.ptr) {
        void* p = nullptr;
        if (cudaSuccess != cudaMalloc(&p, block_bytes_)) {
            return {};
        }
        mem.ptr = p;
        mem.bytes = block_bytes_;
    }
#endif
    return mem;
}

void GpuBufferPool::release(Memory&& mem) {
#if VA_HAS_CUDA_RUNTIME
    if (!mem.ptr) return;
    std::lock_guard<std::mutex> lk(mutex_);
    if (free_.size() < capacity_) {
        free_.push_back(mem);
    } else {
        cudaFree(mem.ptr);
    }
#else
    (void)mem;
#endif
}

} // namespace va::core

