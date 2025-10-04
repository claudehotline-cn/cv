#include "core/buffer_pool.hpp"

#include <algorithm>
#include <cstdlib>

namespace {

struct MallocDeleter {
    void operator()(void* ptr) const noexcept {
        std::free(ptr);
    }
};

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_BUFFER_POOL_HAS_CUDA 1
#    else
#      define VA_BUFFER_POOL_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_BUFFER_POOL_HAS_CUDA 1
#  endif
#else
#  define VA_BUFFER_POOL_HAS_CUDA 0
#endif

#if VA_BUFFER_POOL_HAS_CUDA
struct CudaHostDeleter {
    void operator()(void* ptr) const noexcept {
        if (!ptr) {
            return;
        }
        cudaFreeHost(ptr);
    }
};

struct CudaDeviceDeleter {
    void operator()(void* ptr) const noexcept {
        if (!ptr) {
            return;
        }
        cudaFree(ptr);
    }
};
#endif

using SharedBuffer = std::shared_ptr<void>;

SharedBuffer makeHostBuffer(std::size_t bytes, bool use_pinned) {
#if VA_BUFFER_POOL_HAS_CUDA
    if (use_pinned && bytes > 0) {
        void* pinned = nullptr;
        if (cudaHostAlloc(&pinned, bytes, cudaHostAllocDefault) == cudaSuccess) {
            return SharedBuffer(pinned, CudaHostDeleter{});
        }
    }
#else
    (void)use_pinned;
#endif

    void* buffer = std::malloc(bytes ? bytes : 1);
    if (!buffer) {
        return {};
    }
    return SharedBuffer(buffer, MallocDeleter{});
}

#if VA_BUFFER_POOL_HAS_CUDA
SharedBuffer makeDeviceBuffer(std::size_t bytes) {
    if (bytes == 0) {
        return {};
    }
    void* device_ptr = nullptr;
    if (cudaMalloc(&device_ptr, bytes) != cudaSuccess) {
        return {};
    }
    return SharedBuffer(device_ptr, CudaDeviceDeleter{});
}
#endif

} // namespace

namespace va::core {

MemoryHandle HostBufferPool::acquire() {
    MemoryHandle handle;
    handle.bytes = block_bytes_;
    handle.location = MemoryLocation::Host;

    SharedBuffer buffer;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!free_.empty()) {
            buffer = std::move(free_.front());
            free_.pop();
        }
    }

    if (!buffer) {
        buffer = makeHostBuffer(block_bytes_, use_pinned_);
    }

    if (!buffer) {
        return handle;
    }

    handle.host_owner = buffer;
    handle.host_ptr = buffer.get();
    return handle;
}

void HostBufferPool::release(MemoryHandle&& handle) {
    SharedBuffer owner = std::move(handle.host_owner);
    handle.host_ptr = nullptr;
    if (!owner) {
        return;
    }

    std::lock_guard<std::mutex> lock(mutex_);
    if (free_.size() < capacity_) {
        free_.push(std::move(owner));
    }
}

MemoryHandle GpuBufferPool::acquire() {
    MemoryHandle h;
    h.location = MemoryLocation::Device;
    h.bytes = block_bytes_;
#if VA_BUFFER_POOL_HAS_CUDA
    SharedBuffer buffer;
    {
        std::lock_guard<std::mutex> lock(mutex_);
        if (!free_.empty()) {
            buffer = std::move(free_.front());
            free_.pop();
        }
    }

    if (!buffer) {
        buffer = makeDeviceBuffer(block_bytes_);
    }

    if (buffer) {
        h.device_owner = buffer;
        h.device_ptr = buffer.get();
    }
#endif
    return h;
}

void GpuBufferPool::release(MemoryHandle&& handle) {
#if VA_BUFFER_POOL_HAS_CUDA
    SharedBuffer owner = std::move(handle.device_owner);
    if (!owner) {
        return;
    }
    std::lock_guard<std::mutex> lock(mutex_);
    if (free_.size() < capacity_) {
        free_.push(std::move(owner));
    }
#else
    (void)handle;
#endif
}

} // namespace va::core
