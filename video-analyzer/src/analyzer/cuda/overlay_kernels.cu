#include "analyzer/cuda/overlay_kernels.hpp"

namespace va::analyzer::cudaops {

__device__ inline void put_pixel(uint8_t* img, int w, int h, int x, int y, uint8_t b, uint8_t g, uint8_t r) {
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    size_t idx = (static_cast<size_t>(y) * static_cast<size_t>(w) + static_cast<size_t>(x)) * 3ull;
    img[idx+0] = b; img[idx+1] = g; img[idx+2] = r;
}

// Parallel border drawing: one block per box, threads split scanlines/columns
__global__ void k_draw_rects(uint8_t* img, int w, int h,
                             const float* boxes, const int32_t* classes,
                             int n, int thick) {
    int i = blockIdx.x;
    if (i >= n || thick <= 0) return;

    float x1f = boxes[i*4+0], y1f = boxes[i*4+1], x2f = boxes[i*4+2], y2f = boxes[i*4+3];
    int x1 = (int)roundf(x1f); int y1 = (int)roundf(y1f);
    int x2 = (int)roundf(x2f); int y2 = (int)roundf(y2f);
    if (x2 < x1) { int t = x1; x1 = x2; x2 = t; }
    if (y2 < y1) { int t = y1; y1 = y2; y2 = t; }
    x1 = max(0, min(x1, w-1)); x2 = max(0, min(x2, w-1));
    y1 = max(0, min(y1, h-1)); y2 = max(0, min(y2, h-1));
    if (x2 <= x1 || y2 <= y1) return;

    int cls = classes ? classes[i] : 0;
    uint8_t r = (uint8_t)((37*cls + 97) % 255);
    uint8_t g = (uint8_t)((17*cls + 199) % 255);
    uint8_t b = (uint8_t)((233*cls + 53) % 255);

    // Top/bottom edges: distribute x across threads
    for (int t = 0; t < thick; ++t) {
        int yt = min(y1 + t, h-1);
        int yb = max(y2 - t, 0);
        for (int x = x1 + threadIdx.x; x <= x2; x += blockDim.x) {
            put_pixel(img, w, h, x, yt, b, g, r);
            put_pixel(img, w, h, x, yb, b, g, r);
        }
    }

    // Left/right edges: distribute y across threads
    for (int t = 0; t < thick; ++t) {
        int xl = min(x1 + t, w-1);
        int xr = max(x2 - t, 0);
        for (int y = y1 + threadIdx.x; y <= y2; y += blockDim.x) {
            put_pixel(img, w, h, xl, y, b, g, r);
            put_pixel(img, w, h, xr, y, b, g, r);
        }
    }
}

// Parallel semi-transparent fill: one block per box; threads cover rows
__global__ void k_fill_rects(uint8_t* img, int w, int h,
                              const float* boxes, const int32_t* classes,
                              int n, float alpha) {
    if (alpha <= 0.0f) return;
    int i = blockIdx.x;
    if (i >= n) return;

    float x1f = boxes[i*4+0], y1f = boxes[i*4+1], x2f = boxes[i*4+2], y2f = boxes[i*4+3];
    int x1 = (int)roundf(x1f); int y1 = (int)roundf(y1f);
    int x2 = (int)roundf(x2f); int y2 = (int)roundf(y2f);
    if (x2 < x1) { int t = x1; x1 = x2; x2 = t; }
    if (y2 < y1) { int t = y1; y1 = y2; y2 = t; }
    x1 = max(0, min(x1, w-1)); x2 = max(0, min(x2, w-1));
    y1 = max(0, min(y1, h-1)); y2 = max(0, min(y2, h-1));
    if (x2 <= x1 || y2 <= y1) return;

    int cls = classes ? classes[i] : 0;
    uint8_t r = (uint8_t)((37*cls + 97) % 255);
    uint8_t g = (uint8_t)((17*cls + 199) % 255);
    uint8_t b = (uint8_t)((233*cls + 53) % 255);
    float a = fminf(fmaxf(alpha, 0.0f), 1.0f);

    for (int y = y1 + threadIdx.x; y <= y2; y += blockDim.x) {
        size_t base = (static_cast<size_t>(y) * (size_t)w + (size_t)x1) * 3ull;
        for (int x = x1; x <= x2; ++x) {
            size_t idx = base + static_cast<size_t>(x - x1) * 3ull;
            float cb = img[idx+0] * (1.0f - a) + b * a;
            float cg = img[idx+1] * (1.0f - a) + g * a;
            float cr = img[idx+2] * (1.0f - a) + r * a;
            img[idx+0] = (uint8_t)cb;
            img[idx+1] = (uint8_t)cg;
            img[idx+2] = (uint8_t)cr;
        }
    }
}

cudaError_t draw_rects_bgr_inplace(
    uint8_t* d_bgr,
    int w,
    int h,
    const float* d_boxes,
    const int32_t* d_classes,
    int num,
    int thickness,
    cudaStream_t stream)
{
    if (num <= 0 || thickness <= 0) return cudaSuccess;
    dim3 grid(num), block(256);
    k_draw_rects<<<grid, block, 0, stream>>>(d_bgr, w, h, d_boxes, d_classes, num, thickness);
    return cudaGetLastError();
}

cudaError_t fill_rects_bgr_inplace(
    uint8_t* d_bgr,
    int w,
    int h,
    const float* d_boxes,
    const int32_t* d_classes,
    int num,
    float alpha,
    cudaStream_t stream)
{
    if (num <= 0 || alpha <= 0.0f) return cudaSuccess;
    dim3 grid(num), block(256);
    k_fill_rects<<<grid, block, 0, stream>>>(d_bgr, w, h, d_boxes, d_classes, num, alpha);
    return cudaGetLastError();
}

}

