#include "analyzer/preproc_letterbox_cuda.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"
#include "core/logger.hpp"
#include "core/gpu_buffer_pool.hpp"
#if defined(VA_HAS_CUDA_KERNELS)
#include "analyzer/cuda/preproc_letterbox_kernels.hpp"
#endif

#include <vector>
#include <cmath>

#if defined(USE_CUDA)
#if defined(__has_include)
#  if __has_include(<cuda_runtime.h>)
#    include <cuda_runtime.h>
#    define VA_HAS_CUDA_RUNTIME 1
#  else
#    define VA_HAS_CUDA_RUNTIME 0
#  endif
#else
#  include <cuda_runtime.h>
#  define VA_HAS_CUDA_RUNTIME 1
#endif
#else
#  define VA_HAS_CUDA_RUNTIME 0
#endif

namespace va::analyzer {

LetterboxPreprocessorCUDA::LetterboxPreprocessorCUDA(int input_width, int input_height)
    : input_width_(input_width), input_height_(input_height) {}

LetterboxPreprocessorCUDA::~LetterboxPreprocessorCUDA() {
    releaseDevice();
}

bool LetterboxPreprocessorCUDA::ensureDeviceCapacity(std::size_t bytes) {
#if VA_HAS_CUDA_RUNTIME
    if (bytes == 0) {
        releaseDevice();
        return true;
    }
    if (device_ptr_ && capacity_bytes_ >= bytes) {
        return true;
    }
    // Use GPU buffer pool to acquire/reuse device memory
    if (!out_pool_) {
        out_pool_ = std::make_unique<va::core::GpuBufferPool>(bytes, 4);
    }
    if (out_mem_.ptr && out_mem_.bytes < bytes) {
        // release smaller block back to pool
        out_pool_->release(std::move(out_mem_));
        out_mem_ = {};
    }
    if (!out_mem_.ptr) {
        auto mem = out_pool_->acquire(bytes);
        if (!mem.ptr) {
            device_ptr_ = nullptr;
            capacity_bytes_ = 0;
            return false;
        }
        out_mem_ = mem;
        device_ptr_ = out_mem_.ptr;
        capacity_bytes_ = out_mem_.bytes;
    } else {
        device_ptr_ = out_mem_.ptr;
        capacity_bytes_ = out_mem_.bytes;
    }
    return true;
#else
    (void)bytes;
    return false;
#endif
}

void LetterboxPreprocessorCUDA::releaseDevice() {
#if VA_HAS_CUDA_RUNTIME
    device_ptr_ = nullptr;
    capacity_bytes_ = 0;
    if (out_pool_ && out_mem_.ptr) {
        out_pool_->release(std::move(out_mem_));
        out_mem_ = {};
    }
#endif
}

bool LetterboxPreprocessorCUDA::ensureInputCapacity(std::size_t bytes) {
#if VA_HAS_CUDA_RUNTIME
    if (bytes == 0) { releaseInput(); return true; }
    if (input_device_ptr_ && input_capacity_bytes_ >= bytes) return true;
    if (!in_pool_) {
        in_pool_ = std::make_unique<va::core::GpuBufferPool>(bytes, 4);
    }
    if (in_mem_.ptr && in_mem_.bytes < bytes) {
        in_pool_->release(std::move(in_mem_));
        in_mem_ = {};
    }
    if (!in_mem_.ptr) {
        auto mem = in_pool_->acquire(bytes);
        if (!mem.ptr) { input_device_ptr_ = nullptr; input_capacity_bytes_ = 0; return false; }
        in_mem_ = mem;
        input_device_ptr_ = in_mem_.ptr;
        input_capacity_bytes_ = in_mem_.bytes;
    } else {
        input_device_ptr_ = in_mem_.ptr;
        input_capacity_bytes_ = in_mem_.bytes;
    }
    return true;
#else
    (void)bytes; return false;
#endif
}

void LetterboxPreprocessorCUDA::releaseInput() {
#if VA_HAS_CUDA_RUNTIME
    input_device_ptr_ = nullptr;
    input_capacity_bytes_ = 0;
    if (in_pool_ && in_mem_.ptr) {
        in_pool_->release(std::move(in_mem_));
        in_mem_ = {};
    }
#endif
}

bool LetterboxPreprocessorCUDA::run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) {
    if (in.width <= 0 || in.height <= 0 || (in.bgr.empty() && !in.has_device_surface)) {
        return false;
    }
    if (in.has_device_surface && in.device.on_gpu && in.device.fmt == core::PixelFormat::NV12 &&
        in.device.data0 && in.device.data1 && in.device.width > 0 && in.device.height > 0) {
        // Try device path for NV12 → NCHW(FP32)
        const int out_w = (input_width_ > 0 ? input_width_ : in.device.width);
        const int out_h = (input_height_ > 0 ? input_height_ : in.device.height);
        const float scale = std::min(static_cast<float>(out_w) / static_cast<float>(in.device.width),
                                     static_cast<float>(out_h) / static_cast<float>(in.device.height));
        const int resized_w = static_cast<int>(std::round(in.device.width * scale));
        const int resized_h = static_cast<int>(std::round(in.device.height * scale));
        const int pad_x = (out_w - resized_w) / 2;
        const int pad_y = (out_h - resized_h) / 2;

        meta.input_width = out_w;
        meta.input_height = out_h;
        meta.original_width = in.device.width;
        meta.original_height = in.device.height;
        meta.scale = scale;
        meta.pad_x = pad_x;
        meta.pad_y = pad_y;

#if VA_HAS_CUDA_RUNTIME && defined(VA_HAS_CUDA_KERNELS)
        const std::size_t out_elements = static_cast<std::size_t>(1) * 3ull * static_cast<std::size_t>(out_h) * static_cast<std::size_t>(out_w);
        const std::size_t out_bytes = out_elements * sizeof(float);
        if (ensureDeviceCapacity(out_bytes)) {
            auto err = va::analyzer::cudaops::letterbox_nv12_to_nchw_fp32(
                static_cast<const uint8_t*>(in.device.data0), in.device.pitch0,
                static_cast<const uint8_t*>(in.device.data1), in.device.pitch1,
                in.device.width, in.device.height,
                out_w, out_h,
                static_cast<float*>(device_ptr_),
                scale, pad_x, pad_y,
                true,
                nullptr);
            if (err == cudaSuccess) {
                out.data = device_ptr_;
                out.shape = {1, 3, out_h, out_w};
                out.dtype = core::DType::F32;
                out.on_gpu = true;
                return true;
            }
        }
#endif
        VA_LOG_WARN() << "[PreprocCUDA] NV12 device path failed; falling back to host staging";
    }

    // 目标输出尺寸
    const int out_w = (input_width_ > 0 ? input_width_ : in.width);
    const int out_h = (input_height_ > 0 ? input_height_ : in.height);

    // 计算 letterbox 元信息
    const float scale = std::min(static_cast<float>(out_w) / static_cast<float>(in.width),
                                 static_cast<float>(out_h) / static_cast<float>(in.height));
    const int resized_w = static_cast<int>(std::round(in.width * scale));
    const int resized_h = static_cast<int>(std::round(in.height * scale));
    const int pad_x = (out_w - resized_w) / 2;
    const int pad_y = (out_h - resized_h) / 2;

    meta.input_width = out_w;
    meta.input_height = out_h;
    meta.original_width = in.width;
    meta.original_height = in.height;
    meta.scale = scale;
    meta.pad_x = pad_x;
    meta.pad_y = pad_y;

#if VA_HAS_CUDA_RUNTIME
    const std::size_t out_elements = static_cast<std::size_t>(1) * 3ull * static_cast<std::size_t>(out_h) * static_cast<std::size_t>(out_w);
    const std::size_t out_bytes = out_elements * sizeof(float);
    if (!ensureDeviceCapacity(out_bytes)) {
        // 回退：使用 CPU 预处理
        LetterboxPreprocessorCPU cpu_fallback(out_w, out_h);
        core::TensorView temp;
        if (!cpu_fallback.run(in, temp, meta)) return false;
        out = temp;
        out.on_gpu = false;
        return true;
    }
    // 输入 staging 到设备
    const std::size_t in_bytes = static_cast<std::size_t>(in.width) * static_cast<std::size_t>(in.height) * 3ull;
    if (!ensureInputCapacity(in_bytes)) {
        LetterboxPreprocessorCPU cpu_fallback(out_w, out_h);
        core::TensorView temp;
        if (!cpu_fallback.run(in, temp, meta)) return false;
        out = temp;
        out.on_gpu = false;
        return true;
    }
    cudaError_t err = cudaMemcpy(input_device_ptr_, in.bgr.data(), in_bytes, cudaMemcpyHostToDevice);
    if (err != cudaSuccess) {
        LetterboxPreprocessorCPU cpu_fallback(out_w, out_h);
        core::TensorView temp;
        if (!cpu_fallback.run(in, temp, meta)) return false;
        out = temp;
        out.on_gpu = false;
        return true;
    }

    // 启动 CUDA kernel（使用最近邻采样，后续可升级为双线性）
    #if defined(VA_HAS_CUDA_KERNELS)
    err = va::analyzer::cudaops::letterbox_bgr_to_nchw_fp32(
        static_cast<const uint8_t*>(input_device_ptr_),
        in.width, in.height,
        out_w, out_h,
        static_cast<float*>(device_ptr_),
        scale, pad_x, pad_y,
        true,
        nullptr);
    if (err != cudaSuccess)
    #endif
    {
        LetterboxPreprocessorCPU cpu_fallback(out_w, out_h);
        core::TensorView temp;
        if (!cpu_fallback.run(in, temp, meta)) return false;
        out = temp;
        out.on_gpu = false;
        return true;
    }

    out.data = device_ptr_;
    out.shape = {1, 3, out_h, out_w};
    out.dtype = core::DType::F32;
    out.on_gpu = true;
    return true;
#else
    // 无 CUDA：回退 CPU
    LetterboxPreprocessorCPU cpu_fallback(out_w, out_h);
    core::TensorView temp;
    if (!cpu_fallback.run(in, temp, meta)) return false;
    out = temp;
    out.on_gpu = false;
    return true;
#endif
}

} // namespace va::analyzer
