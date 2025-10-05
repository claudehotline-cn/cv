#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"

namespace va::analyzer::cudaops {

__device__ inline float iou_yxyx(const float* a, const float* b) {
    float x1 = fmaxf(a[0], b[0]);
    float y1 = fmaxf(a[1], b[1]);
    float x2 = fminf(a[2], b[2]);
    float y2 = fminf(a[3], b[3]);
    float w = fmaxf(0.0f, x2 - x1);
    float h = fmaxf(0.0f, y2 - y1);
    float inter = w * h;
    float area_a = fmaxf(0.0f, a[2] - a[0]) * fmaxf(0.0f, a[3] - a[1]);
    float area_b = fmaxf(0.0f, b[2] - b[0]) * fmaxf(0.0f, b[3] - b[1]);
    float uni = area_a + area_b - inter;
    return uni > 0.0f ? inter / uni : 0.0f;
}

// Sequential single-thread NMS for deterministic behavior; assumes boxes sorted by descending score.
__global__ void k_nms_seq_per_class(const float* boxes, const int32_t* classes, int num, float iou_thr, int* keep, int* kept_count) {
    if (blockIdx.x != 0 || threadIdx.x != 0) return;
    // Initialize as kept
    for (int i = 0; i < num; ++i) keep[i] = 1;
    int kept = 0;
    for (int i = 0; i < num; ++i) {
        if (!keep[i]) continue;
        ++kept;
        const float* bi = boxes + i * 4;
        int ci = classes[i];
        for (int j = i + 1; j < num; ++j) {
            if (!keep[j]) continue;
            if (classes[j] != ci) continue;
            const float* bj = boxes + j * 4;
            if (iou_yxyx(bi, bj) > iou_thr) {
                keep[j] = 0;
            }
        }
    }
    if (kept_count) *kept_count = kept;
}

cudaError_t nms_yxyx_per_class(
    const float* d_boxes,
    const float* /*d_scores*/,
    const int32_t* d_classes,
    int num,
    float iou_threshold,
    int* d_keep,
    int* kept_count,
    cudaStream_t stream)
{
    dim3 grid(1), block(1);
    k_nms_seq_per_class<<<grid, block, 0, stream>>>(d_boxes, d_classes, num, iou_threshold, d_keep, kept_count);
    return cudaGetLastError();
}

}
