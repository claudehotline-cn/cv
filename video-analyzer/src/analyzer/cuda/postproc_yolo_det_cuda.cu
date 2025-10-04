#include "analyzer/cuda/postproc_yolo_det_cuda.hpp"

#include <algorithm>
#include <cmath>
#include <vector>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_YOLO_POST_HAS_CUDA 1
#    else
#      define VA_YOLO_POST_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_YOLO_POST_HAS_CUDA 1
#  endif
#else
#  define VA_YOLO_POST_HAS_CUDA 0
#endif

namespace {

[[maybe_unused]] constexpr float kScoreThreshold = 0.25f;
[[maybe_unused]] constexpr float kNmsThreshold = 0.45f;

#if VA_YOLO_POST_HAS_CUDA
struct CudaDeleter {
    void operator()(void* ptr) const noexcept {
        if (ptr) {
            cudaFree(ptr);
        }
    }
};

extern "C" __global__ void yolo_decode_kernel(const float* __restrict__ data,
                                               int num_det,
                                               int num_attrs,
                                               int num_classes,
                                               int channels_first,
                                               float score_threshold,
                                               float inv_scale,
                                               int pad_x,
                                               int pad_y,
                                               float clamp_w,
                                               float clamp_h,
                                               va::analyzer::cuda::DeviceBox* __restrict__ boxes,
                                               int* __restrict__ counter,
                                               int max_boxes);
#endif

} // namespace

namespace va::analyzer::cuda {

bool YoloPostprocessorCUDA::decode(const core::TensorView& tensor,
                                   const core::LetterboxMeta& meta,
                                   std::vector<core::Box>& boxes) {
#if !VA_YOLO_POST_HAS_CUDA
    (void)tensor;
    (void)meta;
    (void)boxes;
    return false;
#else
    if (!tensor.device_data || tensor.dtype != core::DType::F32 || tensor.shape.size() < 3) {
        return false;
    }

    int64_t dim0 = tensor.shape[0];
    int64_t dim1 = tensor.shape[1];
    int64_t dim2 = tensor.shape[2];
    if (dim0 != 1) {
        return false;
    }

    int64_t num_det = 0;
    int64_t num_attrs = 0;
    bool channels_first = false;

    if (dim1 <= dim2) {
        num_det = dim1;
        num_attrs = dim2;
    } else {
        num_det = dim2;
        num_attrs = dim1;
        channels_first = true;
    }

    if (num_attrs < 5 || num_det <= 0) {
        return false;
    }

    const int num_classes = static_cast<int>(num_attrs - 4);
    if (num_classes <= 0) {
        return false;
    }

    const int max_boxes = static_cast<int>(num_det);
    if (!ensureBuffer(boxes_buffer_, sizeof(DeviceBox) * static_cast<std::size_t>(max_boxes))) {
        return false;
    }
    if (!ensureBuffer(counter_buffer_, sizeof(int))) {
        return false;
    }

    if (cudaMemset(counter_buffer_.ptr.get(), 0, sizeof(int)) != cudaSuccess) {
        return false;
    }

    const float scale = meta.scale;
    const float inv_scale = (scale == 0.0f) ? 1.0f : (1.0f / scale);
    const float max_w = meta.original_width > 0 ? static_cast<float>(meta.original_width)
                                                : static_cast<float>(meta.input_width);
    const float max_h = meta.original_height > 0 ? static_cast<float>(meta.original_height)
                                                 : static_cast<float>(meta.input_height);
    const float clamp_w = std::max(0.0f, max_w - 1.0f);
    const float clamp_h = std::max(0.0f, max_h - 1.0f);

    const int threads = 256;
    const int blocks = static_cast<int>((num_det + threads - 1) / threads);

    yolo_decode_kernel<<<blocks, threads>>>(static_cast<const float*>(tensor.device_data),
                                            static_cast<int>(num_det),
                                            static_cast<int>(num_attrs),
                                            num_classes,
                                            channels_first ? 1 : 0,
                                            kScoreThreshold,
                                            inv_scale,
                                            meta.pad_x,
                                            meta.pad_y,
                                            clamp_w,
                                            clamp_h,
                                            static_cast<DeviceBox*>(boxes_buffer_.ptr.get()),
                                            static_cast<int*>(counter_buffer_.ptr.get()),
                                            max_boxes);

    if (cudaPeekAtLastError() != cudaSuccess) {
        return false;
    }

    int host_count = 0;
    if (cudaMemcpy(&host_count, counter_buffer_.ptr.get(), sizeof(int), cudaMemcpyDeviceToHost) != cudaSuccess) {
        return false;
    }

    host_count = std::max(0, std::min(host_count, max_boxes));

    boxes.clear();
    if (host_count == 0) {
        return true;
    }

    if (!launchYoloNms(static_cast<DeviceBox*>(boxes_buffer_.ptr.get()), host_count, kNmsThreshold)) {
        return false;
    }

    std::vector<DeviceBox> host_boxes(static_cast<std::size_t>(host_count));
    if (cudaMemcpy(host_boxes.data(),
                   boxes_buffer_.ptr.get(),
                   sizeof(DeviceBox) * static_cast<std::size_t>(host_count),
                   cudaMemcpyDeviceToHost) != cudaSuccess) {
        return false;
    }

    boxes.reserve(static_cast<std::size_t>(host_count));
    for (const auto& device_box : host_boxes) {
        if (device_box.suppressed != 0) {
            continue;
        }
        core::Box box;
        box.x1 = device_box.x1;
        box.y1 = device_box.y1;
        box.x2 = device_box.x2;
        box.y2 = device_box.y2;
        box.score = device_box.score;
        box.cls = device_box.cls;
        if (box.x2 > box.x1 && box.y2 > box.y1) {
            boxes.emplace_back(box);
        }
    }

    return true;
#endif
}

bool YoloPostprocessorCUDA::ensureBuffer(DeviceBuffer& buffer, std::size_t bytes) {
#if !VA_YOLO_POST_HAS_CUDA
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

} // namespace va::analyzer::cuda
