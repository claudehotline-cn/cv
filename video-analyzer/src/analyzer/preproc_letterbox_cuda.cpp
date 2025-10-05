#include "analyzer/preproc_letterbox_cuda.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"

#include <vector>

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

bool LetterboxPreprocessorCUDA::run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) {
    if (in.width <= 0 || in.height <= 0 || in.bgr.empty()) {
        return false;
    }

    // 1) 先用现有 CPU 逻辑生成 F32 NCHW（保证正确性），随后拷贝到 GPU 内存
    LetterboxPreprocessorCPU cpu(input_width_, input_height_);
    core::TensorView temp;
    if (!cpu.run(in, temp, meta)) {
        return false;
    }

    const std::size_t elements = static_cast<std::size_t>(temp.shape[0]) * static_cast<std::size_t>(temp.shape[1]) *
                                 static_cast<std::size_t>(temp.shape[2]) * static_cast<std::size_t>(temp.shape[3]);
    const std::size_t bytes = elements * sizeof(float);

#if VA_HAS_CUDA_RUNTIME
    if (!ensureDeviceCapacity(bytes)) {
        // 回退：直接返回 CPU 张量（仍可被 ORT 绑定为 pinned/CPU）
        out = temp;
        out.on_gpu = false;
        return true;
    }
    cudaError_t err = cudaMemcpy(device_ptr_, temp.data, bytes, cudaMemcpyHostToDevice);
    if (err != cudaSuccess) {
        // 回退 CPU
        out = temp;
        out.on_gpu = false;
        return true;
    }
    out.data = device_ptr_;
    out.shape = temp.shape;
    out.dtype = core::DType::F32;
    out.on_gpu = true;
    return true;
#else
    // 无 CUDA 运行时：回退 CPU
    out = temp;
    out.on_gpu = false;
    return true;
#endif
}

} // namespace va::analyzer
