#include "analyzer/preproc_letterbox_cuda.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"
#include "core/logger.hpp"
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
    releaseDevice();
    cudaError_t err = cudaMalloc(&device_ptr_, bytes);
    if (err != cudaSuccess) {
        device_ptr_ = nullptr;
        capacity_bytes_ = 0;
        return false;
    }
    capacity_bytes_ = bytes;
    return true;
#else
    (void)bytes;
    return false;
#endif
}

void LetterboxPreprocessorCUDA::releaseDevice() {
#if VA_HAS_CUDA_RUNTIME
    if (device_ptr_) {
        cudaFree(device_ptr_);
        device_ptr_ = nullptr;
        capacity_bytes_ = 0;
    }
#endif
}

bool LetterboxPreprocessorCUDA::ensureInputCapacity(std::size_t bytes) {
#if VA_HAS_CUDA_RUNTIME
    if (bytes == 0) { releaseInput(); return true; }
    if (input_device_ptr_ && input_capacity_bytes_ >= bytes) return true;
    releaseInput();
    cudaError_t err = cudaMalloc(&input_device_ptr_, bytes);
    if (err != cudaSuccess) { input_device_ptr_ = nullptr; input_capacity_bytes_ = 0; return false; }
    input_capacity_bytes_ = bytes;
    return true;
#else
    (void)bytes; return false;
#endif
}

void LetterboxPreprocessorCUDA::releaseInput() {
#if VA_HAS_CUDA_RUNTIME
    if (input_device_ptr_) {
        cudaFree(input_device_ptr_);
        input_device_ptr_ = nullptr;
        input_capacity_bytes_ = 0;
    }
#endif
}

bool LetterboxPreprocessorCUDA::run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) {
    if (in.width <= 0 || in.height <= 0 || (in.bgr.empty() && !in.has_device_surface)) {
        return false;
    }
    if (in.has_device_surface && in.device.on_gpu) {
        VA_LOG_INFO() << "[PreprocCUDA] device surface present (fmt=" << static_cast<int>(in.device.fmt)
                      << ", size=" << in.device.width << "x" << in.device.height << ") - using host staging path";
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
