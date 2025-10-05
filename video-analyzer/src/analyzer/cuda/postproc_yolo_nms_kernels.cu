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

// Parallel pairwise NMS: for each i, suppress if any j has >= score and IoU>thr (same class)
__global__ void k_nms_pairwise(const float* boxes, const float* scores, const int32_t* classes, int num, float iou_thr, int* keep) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= num) return;
    int ci = classes[i];
    const float* bi = boxes + i * 4;
    float si = scores[i];
    int k = 1;
    for (int j=0;j<num;++j){
        if (j==i) continue;
        if (classes[j] != ci) continue;
        if (scores[j] >= si) {
            const float* bj = boxes + j * 4;
            if (iou_yxyx(bi, bj) > iou_thr) { k = 0; break; }
        }
    }
    keep[i] = k;
}

cudaError_t nms_yxyx_per_class(
    const float* d_boxes,
    const float* d_scores,
    const int32_t* d_classes,
    int num,
    float iou_threshold,
    int* d_keep,
    int* kept_count,
    cudaStream_t stream)
{
    int threads = 256;
    int blocks = (num + threads - 1) / threads;
    k_nms_pairwise<<<blocks, threads, 0, stream>>>(d_boxes, d_scores, d_classes, num, iou_threshold, d_keep);
    // Optionally compute kept_count on host later; ignore kept_count here for simplicity
    (void)kept_count;
    return cudaGetLastError();
}

}
