#include "analyzer/cuda/overlay_nv12_kernels.hpp"

#include <cuda_runtime.h>

namespace va { namespace analyzer { namespace cudaops_nv12 {

__device__ __forceinline__ int clampi(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// One block per box; single thread draws borders with simple loops
__global__ void k_draw_rects_nv12(uint8_t* y, int pitchY,
                                  uint8_t* uv, int pitchUV,
                                  int width, int height,
                                  const float* boxes_xyxy,
                                  const int* /*classes*/, int count,
                                  int thickness)
{
    const int i = blockIdx.x;
    if (i >= count) return;
    const float x1f = boxes_xyxy[i*4+0];
    const float y1f = boxes_xyxy[i*4+1];
    const float x2f = boxes_xyxy[i*4+2];
    const float y2f = boxes_xyxy[i*4+3];
    int x1 = clampi((int)roundf(x1f), 0, width-1);
    int y1 = clampi((int)roundf(y1f), 0, height-1);
    int x2 = clampi((int)roundf(x2f), 0, width-1);
    int y2 = clampi((int)roundf(y2f), 0, height-1);
    if (x2 <= x1 || y2 <= y1) return;
    const int t = max(1, thickness);

    // Draw on Y plane: set to bright value (235)
    for (int yy = y1; yy < y1 + t && yy < y2; ++yy) {
        uint8_t* row = y + yy * pitchY;
        for (int xx = x1; xx <= x2; ++xx) row[xx] = 235;
    }
    for (int yy = max(y2 - t + 1, y1); yy <= y2; ++yy) {
        uint8_t* row = y + yy * pitchY;
        for (int xx = x1; xx <= x2; ++xx) row[xx] = 235;
    }
    for (int xx = x1; xx < x1 + t && xx < x2; ++xx) {
        for (int yy = y1; yy <= y2; ++yy) {
            y[yy * pitchY + xx] = 235;
        }
    }
    for (int xx = max(x2 - t + 1, x1); xx <= x2; ++xx) {
        for (int yy = y1; yy <= y2; ++yy) {
            y[yy * pitchY + xx] = 235;
        }
    }

    // UV plane: set neutral 128 on border area (optional)
    // Compute UV coordinates (each UV samples 2x2 luma area)
    const int uv_y1 = y1 / 2;
    const int uv_y2 = y2 / 2;
    const int uv_x1 = x1 / 2;
    const int uv_x2 = x2 / 2;
    for (int uyy = uv_y1; uyy <= uv_y2; ++uyy) {
        uint8_t* row = uv + uyy * pitchUV;
        // Horizontal borders width: map t in luma to ceil(t/2) in chroma
        for (int uxx = uv_x1; uxx <= uv_x2; ++uxx) {
            if (uyy - uv_y1 < max(1, t/2) || uv_y2 - uyy < max(1, t/2) ||
                uxx - uv_x1 < max(1, t/2) || uv_x2 - uxx < max(1, t/2)) {
                // NV12 interleaved: [U,V]
                row[uxx*2+0] = 128;
                row[uxx*2+1] = 128;
            }
        }
    }
}

int draw_rects_nv12_inplace(uint8_t* y, int pitchY,
                            uint8_t* uv, int pitchUV,
                            int width, int height,
                            const float* boxes_xyxy,
                            const int* classes,
                            int count,
                            int thickness)
{
    if (!y || !uv || !boxes_xyxy || count <= 0 || width<=0 || height<=0) return cudaErrorInvalidValue;
    dim3 grid(count);
    dim3 block(1);
    k_draw_rects_nv12<<<grid, block>>>(y, pitchY, uv, pitchUV, width, height, boxes_xyxy, classes, count, thickness);
    return (int)cudaGetLastError();
}

// Simple filled Y with alpha (towards 200), UV kept neutral (128)
__global__ void k_fill_rects_nv12(uint8_t* y, int pitchY,
                                  int width, int height,
                                  const float* boxes_xyxy,
                                  int count,
                                  float alpha)
{
    const int i = blockIdx.x;
    if (i >= count) return;
    const float x1f = boxes_xyxy[i*4+0];
    const float y1f = boxes_xyxy[i*4+1];
    const float x2f = boxes_xyxy[i*4+2];
    const float y2f = boxes_xyxy[i*4+3];
    int x1 = clampi((int)roundf(x1f), 0, width-1);
    int y1 = clampi((int)roundf(y1f), 0, height-1);
    int x2 = clampi((int)roundf(x2f), 0, width-1);
    int y2 = clampi((int)roundf(y2f), 0, height-1);
    if (x2 <= x1 || y2 <= y1) return;
    const float a = fmaxf(0.0f, fminf(alpha, 1.0f));
    for (int yy = y1; yy <= y2; ++yy) {
        uint8_t* row = y + yy * pitchY;
        for (int xx = x1; xx <= x2; ++xx) {
            float v = row[xx] * (1.0f - a) + 200.0f * a;
            row[xx] = (uint8_t)(v > 255.0f ? 255.0f : (v < 0.0f ? 0.0f : v));
        }
    }
}

int fill_rects_nv12_inplace(uint8_t* y, int pitchY,
                            uint8_t* /*uv*/, int /*pitchUV*/,
                            int width, int height,
                            const float* boxes_xyxy,
                            const int* /*classes*/,
                            int count,
                            float alpha)
{
    if (!y || !boxes_xyxy || count <= 0 || width<=0 || height<=0) return cudaErrorInvalidValue;
    dim3 grid(count);
    dim3 block(1);
    k_fill_rects_nv12<<<grid, block>>>(y, pitchY, width, height, boxes_xyxy, count, alpha);
    return (int)cudaGetLastError();
}

} } } // namespace

