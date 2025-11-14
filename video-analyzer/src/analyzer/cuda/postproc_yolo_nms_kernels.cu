#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"

#include <cmath>
#include <thrust/device_ptr.h>
#include <thrust/execution_policy.h>
#include <thrust/sequence.h>
#include <thrust/sort.h>

namespace va::analyzer::cudaops {

namespace {

// 与 CPU 版本一致的 IoU 定义：
// inter / (area_a + area_b - inter)；若 union<=0 则返回 0。
__device__ __forceinline__ float iou_yxyx(const float* a, const float* b) {
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

// 排序用索引比较器：按 score 降序，其次 class，再按坐标，最后按原始 index 升序。
struct IndexLess {
    const float* scores;
    const float* boxes;   // [N,4] yxyx
    const int32_t* classes;

    __host__ __device__ bool operator()(int a, int b) const {
        constexpr float EPS = 1e-6f;
        float sa = scores[a];
        float sb = scores[b];
        float ds = fabsf(sa - sb);
        if (ds > EPS) {
            // score 降序
            return sa > sb;
        }
        int ca = classes[a];
        int cb = classes[b];
        if (ca != cb) {
            return ca < cb;
        }
        const float* ba = boxes + a * 4;
        const float* bb = boxes + b * 4;
        float ax1 = ba[0], ay1 = ba[1], ax2 = ba[2], ay2 = ba[3];
        float bx1 = bb[0], by1 = bb[1], bx2 = bb[2], by2 = bb[3];
        if (fabsf(ax1 - bx1) > EPS) return ax1 < bx1;
        if (fabsf(ay1 - by1) > EPS) return ay1 < by1;
        if (fabsf(ax2 - bx2) > EPS) return ax2 < bx2;
        if (fabsf(ay2 - by2) > EPS) return ay2 < by2;
        // 原始 index 兜底，保证稳定
        return a < b;
    }
};

constexpr int TILE = 64;

// 构建上三角 IoU 抑制 bitmask：
// - row: 排序后索引 i
// - col_block: 列方向 tiles
// 每个 (row,col_block) 由一个 block 负责；block 内线程计算当前 tile 内 IoU，并在 shared mask 上置位。
__global__ void build_masks_kernel(const float* __restrict__ boxes,
                                   const int32_t* __restrict__ classes,
                                   const int* __restrict__ order,
                                   int n, float iou_thr,
                                   unsigned long long* __restrict__ masks,
                                   int col_blocks) {
    int row = blockIdx.y;
    int col_block = blockIdx.x;
    int tid = threadIdx.x; // 0..TILE-1

    if (row >= n) return;

    __shared__ unsigned long long s_mask;
    if (tid == 0) s_mask = 0ULL;
    __syncthreads();

    int row_idx = order[row];
    const float* bi = boxes + row_idx * 4;
    int cls_row = classes[row_idx];

    int col = col_block * TILE + tid;
    if (col < n && col > row) {
        int col_idx = order[col];
        if (classes[col_idx] == cls_row) {
            const float* bj = boxes + col_idx * 4;
            float iou = iou_yxyx(bi, bj);
            if (iou > iou_thr) {
                // 在 shared 掩码上按位 OR，限定在当前 tile 内
                unsigned long long bit = 1ULL << (col % TILE);
                atomicOr(&s_mask, bit);
            }
        }
    }
    __syncthreads();

    if (tid == 0) {
        masks[row * col_blocks + col_block] = s_mask;
    }
}

// 顺序扫描 masks，按 i=0..n-1 选择保留的索引，并在 keep_mask[orig_idx] 上置 1。
__global__ void reduce_keep_kernel(const unsigned long long* __restrict__ masks,
                                   const int* __restrict__ order,
                                   int n, int col_blocks,
                                   int* __restrict__ keep_mask,
                                   int* __restrict__ keep_count) {
    if (blockIdx.x != 0 || threadIdx.x != 0) return;

    extern __shared__ unsigned long long remv[]; // [col_blocks]
    for (int i = 0; i < col_blocks; ++i) {
        remv[i] = 0ULL;
    }

    int num = 0;
    for (int i = 0; i < n; ++i) {
        int cb = i / TILE;
        int off = i % TILE;
        // 如果当前 i 未被任何已选中的框抑制，则保留
        if ((remv[cb] & (1ULL << off)) == 0ULL) {
            int orig = order[i];
            keep_mask[orig] = 1;
            const unsigned long long* row = masks + i * col_blocks;
            // 将第 i 行的抑制造作 OR 进 remv
            for (int j = cb; j < col_blocks; ++j) {
                remv[j] |= row[j];
            }
            ++num;
        }
    }
    if (keep_count) {
        *keep_count = num;
    }
}

} // namespace

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
    if (num <= 0) {
        if (kept_count) {
            // 当 CUDA 可用时，返回一个有效但空的结果
            *kept_count = 0;
        }
        return cudaSuccess;
    }

    cudaError_t last_err = cudaSuccess;
    int* d_order = nullptr;
    unsigned long long* d_masks = nullptr;
    int col_blocks = 0;

    // 1) 构建索引数组 [0..num-1]
    if (cudaMalloc(&d_order, static_cast<size_t>(num) * sizeof(int)) != cudaSuccess) {
        last_err = cudaGetLastError();
        goto CLEANUP;
    }
    {
        thrust::device_ptr<int> ord(d_order);
        thrust::sequence(thrust::cuda::par.on(stream), ord, ord + num);
    }

    // 2) 稳定排序索引，按 score desc / class / 坐标 / 原始 index
    {
        IndexLess cmp{d_scores, d_boxes, d_classes};
        thrust::device_ptr<int> ord(d_order);
        thrust::stable_sort(thrust::cuda::par.on(stream), ord, ord + num, cmp);
    }

    // 3) 构建 IoU bitmask 矩阵
    col_blocks = (num + TILE - 1) / TILE;
    if (cudaMalloc(&d_masks,
                   static_cast<size_t>(num) * static_cast<size_t>(col_blocks) * sizeof(unsigned long long)) != cudaSuccess) {
        last_err = cudaGetLastError();
        goto CLEANUP;
    }
    if (cudaMemsetAsync(d_masks, 0, static_cast<size_t>(num) * static_cast<size_t>(col_blocks) * sizeof(unsigned long long), stream) != cudaSuccess) {
        last_err = cudaGetLastError();
        goto CLEANUP;
    }

    {
        dim3 block(TILE);
        dim3 grid(col_blocks, num);
        build_masks_kernel<<<grid, block, 0, stream>>>(d_boxes, d_classes, d_order, num, iou_threshold, d_masks, col_blocks);
        last_err = cudaGetLastError();
        if (last_err != cudaSuccess) goto CLEANUP;
    }

    // 4) 初始化 keep mask 为 0，并顺序扫描 masks 生成最终的 keep_mask（按原始索引）
    if (cudaMemsetAsync(d_keep, 0, static_cast<size_t>(num) * sizeof(int), stream) != cudaSuccess) {
        last_err = cudaGetLastError();
        goto CLEANUP;
    }
    {
        size_t shmem_bytes = static_cast<size_t>(col_blocks) * sizeof(unsigned long long);
        reduce_keep_kernel<<<1, 1, shmem_bytes, stream>>>(d_masks, d_order, num, col_blocks, d_keep, kept_count);
        last_err = cudaGetLastError();
        if (last_err != cudaSuccess) goto CLEANUP;
    }

CLEANUP:
    if (d_masks) cudaFree(d_masks);
    if (d_order) cudaFree(d_order);
    return last_err;
}

} // namespace va::analyzer::cudaops
