#include "core/utils.hpp"

#include <cstring>
#include <cstdlib>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_UTILS_HAS_CUDA 1
#    else
#      define VA_UTILS_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_UTILS_HAS_CUDA 1
#  endif
#else
#  define VA_UTILS_HAS_CUDA 0
#endif

namespace va::core {

namespace {

struct MallocDeleter {
    void operator()(void* ptr) const noexcept {
        std::free(ptr);
    }
};

#if VA_UTILS_HAS_CUDA
struct CudaDeleter {
    void operator()(void* ptr) const noexcept {
        if (!ptr) {
            return;
        }
        cudaError_t err = cudaFree(ptr);
        if (err != cudaSuccess) {
            // Avoid throwing inside deleter; logging handled elsewhere if needed
        }
    }
};
#endif

} // namespace

bool MemoryHandle::ensureHost() {
    if (host_ptr) {
        return true;
    }
    if (bytes == 0 || !device_ptr) {
        return false;
    }

#if VA_UTILS_HAS_CUDA
    if (!host_owner) {
        void* buffer = std::malloc(bytes);
        if (!buffer) {
            return false;
        }
        host_owner.reset(buffer, MallocDeleter{});
        host_ptr = buffer;
    }
    cudaError_t err = cudaMemcpy(host_ptr, device_ptr, bytes, cudaMemcpyDeviceToHost);
    if (err != cudaSuccess) {
        return false;
    }
    location = MemoryLocation::Host;
    return true;
#else
    return false;
#endif
}

bool MemoryHandle::ensureDevice() {
    if (device_ptr) {
        return true;
    }

#if VA_UTILS_HAS_CUDA
    if (bytes == 0) {
        return false;
    }
    void* device_buffer = nullptr;
    cudaError_t alloc_err = cudaMalloc(&device_buffer, bytes);
    if (alloc_err != cudaSuccess) {
        return false;
    }
    device_owner.reset(device_buffer, CudaDeleter{});
    device_ptr = device_buffer;

    if (host_ptr) {
        cudaError_t copy_err = cudaMemcpy(device_ptr, host_ptr, bytes, cudaMemcpyHostToDevice);
        if (copy_err != cudaSuccess) {
            device_owner.reset();
            device_ptr = nullptr;
            return false;
        }
    }
    location = MemoryLocation::Device;
    return true;
#else
    return false;
#endif
}

FrameSurface makeSurfaceFromFrame(const Frame& frame) {
    if (frame.has_surface && surfaceHasData(frame.surface)) {
        return frame.surface;
    }

    FrameSurface surface;
    surface.width = frame.width;
    surface.height = frame.height;
    surface.pts_ms = frame.pts_ms;

    surface.handle.host_ptr = frame.bgr.empty() ? nullptr : const_cast<uint8_t*>(frame.bgr.data());
    surface.handle.device_ptr = nullptr;
    surface.handle.bytes = frame.bgr.size();
    surface.handle.pitch = frame.width > 0 ? static_cast<std::size_t>(frame.width) * 3u : 0u;
    surface.handle.width = frame.width;
    surface.handle.height = frame.height;
    surface.handle.stream = nullptr;
    surface.handle.location = MemoryLocation::Host;
    surface.handle.format = PixelFormat::BGR24;
    return surface;
}

bool surfaceToFrame(const FrameSurface& surface, Frame& out) {
    if (surface.width <= 0 || surface.height <= 0) {
        return false;
    }

    auto& handle = const_cast<MemoryHandle&>(surface.handle);
    if (!handle.ensureHost() || handle.host_ptr == nullptr || handle.bytes == 0) {
        return false;
    }

    out.width = surface.width;
    out.height = surface.height;
    out.pts_ms = surface.pts_ms;
    out.bgr.resize(handle.bytes);
    std::memcpy(out.bgr.data(), handle.host_ptr, handle.bytes);
    out.surface = surface;
    out.has_surface = true;
    return true;
}

bool surfaceHasData(const FrameSurface& surface) {
    return (surface.handle.host_ptr != nullptr || surface.handle.device_ptr != nullptr) && surface.handle.bytes > 0;
}

} // namespace va::core
