#include "analyzer/preproc_letterbox_cuda.hpp"

#include "core/utils.hpp"

#include <algorithm>
#include <cmath>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_LETTERBOX_HAS_CUDA 1
#    else
#      define VA_LETTERBOX_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_LETTERBOX_HAS_CUDA 1
#  endif
#else
#  define VA_LETTERBOX_HAS_CUDA 0
#endif

namespace {
#if VA_LETTERBOX_HAS_CUDA
struct CudaDeleter {
    void operator()(void* ptr) const noexcept {
        if (ptr) {
            cudaFree(ptr);
        }
    }
};

extern "C" __global__ void nv12_to_rgb_planar_kernel(const unsigned char* __restrict__ y_plane,
                                                     const unsigned char* __restrict__ uv_plane,
                                                     int width,
                                                     int height,
                                                     int pitch_y,
                                                     int pitch_uv,
                                                     float* __restrict__ dst);

extern "C" __global__ void letterbox_resize_kernel(const float* __restrict__ src,
                                                    int src_width,
                                                    int src_height,
                                                    float* __restrict__ dst,
                                                    int dst_width,
                                                    int dst_height,
                                                    float scale,
                                                    int pad_x,
                                                    int pad_y);
#endif
} // namespace

namespace va::analyzer {

LetterboxPreprocessorCUDA::LetterboxPreprocessorCUDA(int input_width, int input_height)
    : input_width_(input_width), input_height_(input_height), cpu_fallback_(input_width, input_height) {}

bool LetterboxPreprocessorCUDA::run(const core::Frame& in,
                                    core::TensorView& out,
                                    core::LetterboxMeta& meta) {
    return cpu_fallback_.run(in, out, meta);
}

bool LetterboxPreprocessorCUDA::run(const core::FrameSurface& in,
                                    core::TensorView& out,
                                    core::LetterboxMeta& meta) {
    if (!runGpu(in, out, meta)) {
        core::Frame frame;
        if (!va::core::surfaceToFrame(in, frame)) {
            return false;
        }
        return cpu_fallback_.run(frame, out, meta);
    }
    return true;
}

bool LetterboxPreprocessorCUDA::runGpu(const core::FrameSurface& in,
                                       core::TensorView& out,
                                       core::LetterboxMeta& meta) {
#if !VA_LETTERBOX_HAS_CUDA
    (void)in;
    (void)out;
    (void)meta;
    return false;
#else
    const core::MemoryHandle& handle = in.handle;
    if (!handle.device_ptr || handle.format != core::PixelFormat::NV12) {
        return false;
    }

    const int src_width = in.width;
    const int src_height = in.height;
    if (src_width <= 0 || src_height <= 0) {
        return false;
    }

    const int dst_width = input_width_ > 0 ? input_width_ : src_width;
    const int dst_height = input_height_ > 0 ? input_height_ : src_height;

    const float scale = std::min(static_cast<float>(dst_width) / static_cast<float>(src_width),
                                 static_cast<float>(dst_height) / static_cast<float>(src_height));
    const int resized_w = static_cast<int>(std::round(src_width * scale));
    const int resized_h = static_cast<int>(std::round(src_height * scale));

    meta.scale = scale;
    meta.pad_x = (dst_width - resized_w) / 2;
    meta.pad_y = (dst_height - resized_h) / 2;
    meta.input_width = dst_width;
    meta.input_height = dst_height;
    meta.original_width = src_width;
    meta.original_height = src_height;

    const int pitch_y = handle.pitch > 0 ? static_cast<int>(handle.pitch) : src_width;
    const unsigned char* y_plane = static_cast<const unsigned char*>(handle.device_ptr);
    const unsigned char* uv_plane = y_plane + pitch_y * src_height;

    const std::size_t rgb_bytes = static_cast<std::size_t>(src_width) * static_cast<std::size_t>(src_height) * 3ull * sizeof(float);
    if (!ensureBuffer(rgb_buffer_, rgb_bytes)) {
        return false;
    }

    const std::size_t tensor_bytes = static_cast<std::size_t>(dst_width) * static_cast<std::size_t>(dst_height) * 3ull * sizeof(float);
    if (!ensureBuffer(tensor_buffer_, tensor_bytes)) {
        return false;
    }

    float* rgb_ptr = static_cast<float*>(rgb_buffer_.ptr.get());
    float* tensor_ptr = static_cast<float*>(tensor_buffer_.ptr.get());

    dim3 block(16, 16);
    dim3 grid((src_width + block.x - 1) / block.x,
              (src_height + block.y - 1) / block.y);

    nv12_to_rgb_planar_kernel<<<grid, block>>>(y_plane,
                                               uv_plane,
                                               src_width,
                                               src_height,
                                               pitch_y,
                                               pitch_y,
                                               rgb_ptr);
    if (cudaPeekAtLastError() != cudaSuccess) {
        return false;
    }

    dim3 resize_grid((dst_width + block.x - 1) / block.x,
                     (dst_height + block.y - 1) / block.y);
    letterbox_resize_kernel<<<resize_grid, block>>>(rgb_ptr,
                                                    src_width,
                                                    src_height,
                                                    tensor_ptr,
                                                    dst_width,
                                                    dst_height,
                                                    scale,
                                                    meta.pad_x,
                                                    meta.pad_y);
    if (cudaPeekAtLastError() != cudaSuccess) {
        return false;
    }

    out.on_gpu = true;
    out.device_data = tensor_ptr;
    out.data = nullptr;
    out.shape = {1, 3, dst_height, dst_width};
    out.dtype = core::DType::F32;
    out.bytes = tensor_bytes;
    out.handle.device_ptr = tensor_ptr;
    out.handle.device_owner = tensor_buffer_.ptr;
    out.handle.bytes = tensor_bytes;
    out.handle.pitch = 0;
    out.handle.width = dst_width;
    out.handle.height = dst_height;
    out.handle.location = core::MemoryLocation::Device;
    out.handle.format = core::PixelFormat::Unknown;
    out.handle.host_ptr = nullptr;
    out.handle.host_owner.reset();

    return true;
#endif
}

bool LetterboxPreprocessorCUDA::ensureBuffer(DeviceBuffer& buffer, std::size_t bytes) {
#if !VA_LETTERBOX_HAS_CUDA
    (void)buffer;
    (void)bytes;
    return false;
#else
    if (bytes == 0) {
        return false;
    }
    if (!buffer.ptr || buffer.capacity < bytes) {
        void* ptr = nullptr;
        if (cudaMalloc(&ptr, bytes) != cudaSuccess) {
            buffer.ptr.reset();
            buffer.capacity = 0;
            return false;
        }
        buffer.ptr.reset(ptr, CudaDeleter{});
        buffer.capacity = bytes;
    }
    return true;
#endif
}

} // namespace va::analyzer
