#include "analyzer/cuda/postproc_yolo_det_cuda.hpp"

#include <cuda_runtime.h>

__device__ inline float clampf(float value, float lo, float hi) {
    return fminf(fmaxf(value, lo), hi);
}

__device__ inline float valueAt(const float* data,
                                int det_idx,
                                int attr,
                                int num_det,
                                int num_attrs,
                                int channels_first) {
    if (channels_first) {
        return data[attr * num_det + det_idx];
    }
    return data[det_idx * num_attrs + attr];
}

using va::analyzer::cuda::DeviceBox;

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
                                               int max_boxes) {
    const int det_idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (det_idx >= num_det) {
        return;
    }

    const float cx = valueAt(data, det_idx, 0, num_det, num_attrs, channels_first);
    const float cy = valueAt(data, det_idx, 1, num_det, num_attrs, channels_first);
    const float w = valueAt(data, det_idx, 2, num_det, num_attrs, channels_first);
    const float h = valueAt(data, det_idx, 3, num_det, num_attrs, channels_first);

    float best_score = 0.0f;
    int best_class = -1;
    for (int cls = 0; cls < num_classes; ++cls) {
        const float cls_score = valueAt(data, det_idx, 4 + cls, num_det, num_attrs, channels_first);
        if (cls_score > best_score) {
            best_score = cls_score;
            best_class = cls;
        }
    }

    if (best_class < 0 || best_score < score_threshold) {
        return;
    }

    const float half_w = 0.5f * w;
    const float half_h = 0.5f * h;

    const float x1 = cx - half_w;
    const float y1 = cy - half_h;
    const float x2 = cx + half_w;
    const float y2 = cy + half_h;

    const float orig_x1 = (x1 - static_cast<float>(pad_x)) * inv_scale;
    const float orig_y1 = (y1 - static_cast<float>(pad_y)) * inv_scale;
    const float orig_x2 = (x2 - static_cast<float>(pad_x)) * inv_scale;
    const float orig_y2 = (y2 - static_cast<float>(pad_y)) * inv_scale;

    const float clamped_x1 = clampf(orig_x1, 0.0f, clamp_w);
    const float clamped_y1 = clampf(orig_y1, 0.0f, clamp_h);
    const float clamped_x2 = clampf(orig_x2, 0.0f, clamp_w);
    const float clamped_y2 = clampf(orig_y2, 0.0f, clamp_h);

    if (clamped_x2 <= clamped_x1 || clamped_y2 <= clamped_y1) {
        return;
    }

    const int write_idx = atomicAdd(counter, 1);
    if (write_idx >= max_boxes) {
        return;
    }

    boxes[write_idx].x1 = clamped_x1;
    boxes[write_idx].y1 = clamped_y1;
    boxes[write_idx].x2 = clamped_x2;
    boxes[write_idx].y2 = clamped_y2;
    boxes[write_idx].score = best_score;
    boxes[write_idx].cls = best_class;
    boxes[write_idx].suppressed = 0;
}

namespace va::analyzer::cuda {

__device__ inline float box_area(const DeviceBox& box) {
    const float w = fmaxf(0.0f, box.x2 - box.x1);
    const float h = fmaxf(0.0f, box.y2 - box.y1);
    return w * h;
}

__global__ void yolo_nms_kernel(DeviceBox* boxes,
                                int count,
                                float iou_threshold) {
    const int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= count) {
        return;
    }

    DeviceBox self = boxes[idx];
    if (self.score <= 0.0f) {
        boxes[idx].suppressed = 1;
        return;
    }

    const float area_self = box_area(self);
    for (int j = 0; j < count; ++j) {
        if (j == idx) {
            continue;
        }
        const DeviceBox other = boxes[j];
        if (other.cls != self.cls) {
            continue;
        }
        if (other.score < self.score) {
            continue;
        }
        if (other.score == self.score && j < idx) {
            continue;
        }

        const float x1 = fmaxf(self.x1, other.x1);
        const float y1 = fmaxf(self.y1, other.y1);
        const float x2 = fminf(self.x2, other.x2);
        const float y2 = fminf(self.y2, other.y2);
        const float w = fmaxf(0.0f, x2 - x1);
        const float h = fmaxf(0.0f, y2 - y1);
        const float inter = w * h;
        if (inter <= 0.0f) {
            continue;
        }
        const float area_other = box_area(other);
        const float uni = area_self + area_other - inter;
        if (uni <= 0.0f) {
            continue;
        }
        const float iou = inter / uni;
        if (iou > iou_threshold) {
            boxes[idx].suppressed = 1;
            return;
        }
    }

    boxes[idx].suppressed = 0;
}

bool launchYoloNms(DeviceBox* boxes,
                   int count,
                   float iou_threshold) {
    if (!boxes || count <= 0) {
        return true;
    }

    const int threads = 64;
    const int blocks = (count + threads - 1) / threads;
    yolo_nms_kernel<<<blocks, threads>>>(boxes, count, iou_threshold);
    return cudaPeekAtLastError() == cudaSuccess;
}

} // namespace va::analyzer::cuda
