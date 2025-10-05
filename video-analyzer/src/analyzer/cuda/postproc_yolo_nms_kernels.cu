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

// Block-per-box tiled NMS: assumes inputs sorted by descending score on host.
// For each i, compare only with j < i in same class. Threads in the block stride j.
__global__ void k_nms_pairwise_tiled(const float* boxes, const float* scores,
                                     const int32_t* classes, int num, float iou_thr, int* keep) {
    int i = blockIdx.x;
    if (i >= num) return;
    int ci = classes[i];
    const float* bi = boxes + i * 4;
    (void)scores; // sorted by host; compare only j<i
    __shared__ int suppressed;
    suppressed = 0;
    __syncthreads();
    // stride j domain across threads
    for (int j = threadIdx.x; j < i; j += blockDim.x) {
        if (suppressed) break;
        if (classes[j] != ci) continue;
        const float* bj = boxes + j * 4;
        if (iou_yxyx(bi, bj) > iou_thr) {
            suppressed = 1;
            break;
        }
    }
    __syncthreads();
    if (threadIdx.x == 0) {
        keep[i] = suppressed ? 0 : 1;
    }
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
    if (num <= 0) return cudaSuccess;
    int threads = 256; // per i
    int blocks = num;
    k_nms_pairwise_tiled<<<blocks, threads, 0, stream>>>(d_boxes, d_scores, d_classes, num, iou_threshold, d_keep);
    // Optionally compute kept_count on host later; ignore kept_count here for simplicity
    (void)kept_count;
    return cudaGetLastError();
}

}
