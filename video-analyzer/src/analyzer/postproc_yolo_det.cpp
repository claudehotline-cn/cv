#include "analyzer/postproc_yolo_det.hpp"

#include <algorithm>
#include <cmath>
#include <functional>
#include <numeric>
#include <vector>

namespace {

constexpr float kScoreThreshold = 0.25f;
constexpr float kNMSThreshold = 0.45f;

float clamp(float v, float lo, float hi) {
    return std::max(lo, std::min(v, hi));
}

float iou(const va::core::Box& a, const va::core::Box& b) {
    const float x1 = std::max(a.x1, b.x1);
    const float y1 = std::max(a.y1, b.y1);
    const float x2 = std::min(a.x2, b.x2);
    const float y2 = std::min(a.y2, b.y2);

    const float w = std::max(0.0f, x2 - x1);
    const float h = std::max(0.0f, y2 - y1);
    const float inter = w * h;
    const float union_area = (a.x2 - a.x1) * (a.y2 - a.y1) + (b.x2 - b.x1) * (b.y2 - b.y1) - inter;
    if (union_area <= 0.0f) {
        return 0.0f;
    }
    return inter / union_area;
}

void nonMaxSuppression(std::vector<va::core::Box>& boxes) {
    std::vector<size_t> order(boxes.size());
    std::iota(order.begin(), order.end(), 0);
    std::sort(order.begin(), order.end(), [&](size_t lhs, size_t rhs) {
        return boxes[lhs].score > boxes[rhs].score;
    });

    std::vector<bool> suppressed(boxes.size(), false);
    std::vector<va::core::Box> result;
    for (size_t i = 0; i < order.size(); ++i) {
        const size_t idx = order[i];
        if (suppressed[idx]) {
            continue;
        }
        const va::core::Box& candidate = boxes[idx];
        result.push_back(candidate);
        for (size_t j = i + 1; j < order.size(); ++j) {
            const size_t idx2 = order[j];
            if (suppressed[idx2]) {
                continue;
            }
            if (candidate.cls != boxes[idx2].cls) {
                continue;
            }
            if (iou(candidate, boxes[idx2]) > kNMSThreshold) {
                suppressed[idx2] = true;
            }
        }
    }

    boxes.swap(result);
}

} // namespace

namespace va::analyzer {

bool YoloDetectionPostprocessor::run(const std::vector<core::TensorView>& raw_outputs,
                                     const core::LetterboxMeta& meta,
                                     core::ModelOutput& output) {
    output.boxes.clear();
    output.masks.clear();

    if (raw_outputs.empty()) {
        return false;
    }

    const core::TensorView& tensor = raw_outputs.front();
    if (!tensor.data || tensor.shape.size() < 3) {
        return false;
    }

    const float* data = static_cast<const float*>(tensor.data);
    int64_t dim0 = tensor.shape[0];
    int64_t dim1 = tensor.shape[1];
    int64_t dim2 = tensor.shape[2];

    if (dim0 != 1) {
        return false;
    }

    int64_t num_det = 0;
    int64_t num_attrs = 0;
    bool channels_first = false; // indicates layout [C, N]

    if (dim1 <= dim2) {
        num_det = dim1;
        num_attrs = dim2;
    } else {
        num_det = dim2;
        num_attrs = dim1;
        channels_first = true;
    }

    if (num_attrs < 5) {
        return false;
    }

    const int num_classes = static_cast<int>(num_attrs - 4);
    const float scale = meta.scale == 0.0f ? 1.0f : meta.scale;

    std::vector<core::Box> boxes;
    boxes.reserve(static_cast<size_t>(num_det));

    for (int64_t i = 0; i < num_det; ++i) {
        auto value_at = [&](int64_t attr) -> float {
            if (channels_first) {
                return data[attr * num_det + i];
            }
            return data[i * num_attrs + attr];
        };

        const float cx = value_at(0);
        const float cy = value_at(1);
        const float w = value_at(2);
        const float h = value_at(3);

        float best_score = 0.0f;
        int best_class = -1;
        for (int cls = 0; cls < num_classes; ++cls) {
            const float cls_score = value_at(4 + cls);
            if (cls_score > best_score) {
                best_score = cls_score;
                best_class = cls;
            }
        }

        if (best_class < 0 || best_score < kScoreThreshold) {
            continue;
        }

        const float x1 = cx - w * 0.5f;
        const float y1 = cy - h * 0.5f;
        const float x2 = cx + w * 0.5f;
        const float y2 = cy + h * 0.5f;

        const float orig_x1 = (x1 - static_cast<float>(meta.pad_x)) / scale;
        const float orig_y1 = (y1 - static_cast<float>(meta.pad_y)) / scale;
        const float orig_x2 = (x2 - static_cast<float>(meta.pad_x)) / scale;
        const float orig_y2 = (y2 - static_cast<float>(meta.pad_y)) / scale;

        const float max_w = meta.original_width > 0 ? static_cast<float>(meta.original_width) : static_cast<float>(meta.input_width);
        const float max_h = meta.original_height > 0 ? static_cast<float>(meta.original_height) : static_cast<float>(meta.input_height);

        core::Box box;
        box.x1 = clamp(orig_x1, 0.0f, std::max(0.0f, max_w - 1.0f));
        box.y1 = clamp(orig_y1, 0.0f, std::max(0.0f, max_h - 1.0f));
        box.x2 = clamp(orig_x2, 0.0f, std::max(0.0f, max_w - 1.0f));
        box.y2 = clamp(orig_y2, 0.0f, std::max(0.0f, max_h - 1.0f));
        box.score = best_score;
        box.cls = best_class;

        if (box.x2 > box.x1 && box.y2 > box.y1) {
            boxes.emplace_back(box);
        }
    }

    if (boxes.empty()) {
        return true;
    }

    nonMaxSuppression(boxes);
    output.boxes = std::move(boxes);
    return true;
}

} // namespace va::analyzer

#ifdef USE_CUDA
#include "analyzer/postproc_yolo_det.hpp"

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

namespace va::analyzer {

bool YoloDetectionPostprocessorCUDA::run(const std::vector<core::TensorView>& raw_outputs,
                                         const core::LetterboxMeta& meta,
                                         core::ModelOutput& output) {
    // If no outputs or not a tensor-like shape, fallback
    if (raw_outputs.empty()) {
        return false;
    }
    const core::TensorView& t = raw_outputs.front();
    if (t.shape.size() < 3) {
        YoloDetectionPostprocessor cpu;
        return cpu.run(raw_outputs, meta, output);
    }

    // If already on CPU, reuse CPU implementation
    if (!t.on_gpu) {
        YoloDetectionPostprocessor cpu;
        return cpu.run(raw_outputs, meta, output);
    }

#if VA_HAS_CUDA_RUNTIME
    // Copy device tensor to host buffer, then reuse CPU decoder on the host view
    size_t count = 1;
    for (auto d : t.shape) { count *= static_cast<size_t>(d > 0 ? d : 1); }
    if (count == 0) {
        return false;
    }
    std::vector<float> host(count);
    cudaError_t err = cudaMemcpy(host.data(), t.data, count * sizeof(float), cudaMemcpyDeviceToHost);
    if (err != cudaSuccess) {
        // If D2H fails, fallback to CPU impl which will fail on device pointer; return false instead
        return false;
    }

    core::TensorView host_view;
    host_view.data = host.data();
    host_view.shape = t.shape;
    host_view.dtype = core::DType::F32;
    host_view.on_gpu = false;

    std::vector<core::TensorView> wrapped{host_view};
    YoloDetectionPostprocessor cpu;
    const bool ok = cpu.run(wrapped, meta, output);
    return ok;
#else
    // No CUDA runtime – cannot D2H; fallback to CPU decoder (will fail on device ptr), so return false
    return false;
#endif
}

} // namespace va::analyzer
#endif
