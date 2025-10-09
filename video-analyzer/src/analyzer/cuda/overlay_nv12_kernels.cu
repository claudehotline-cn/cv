#include "analyzer/cuda/overlay_nv12_kernels.hpp"

#include <cuda_runtime.h>

namespace va { namespace analyzer { namespace cudaops_nv12 {

__device__ __forceinline__ int clampi(int v, int lo, int hi) {
    return v < lo ? lo : (v > hi ? hi : v);
}

// sRGB->linear helper
__device__ __forceinline__ float srgb_to_lin(float c) {
    return c <= 0.04045f ? c / 12.92f : powf((c + 0.055f) / 1.055f, 2.4f);
}

// Convert sRGB 0..255 to BT.709 limited-range YUV (Y:16..235, U/V:16..240)
__device__ __forceinline__ void rgb_to_yuv709_limited(unsigned char R8, unsigned char G8, unsigned char B8,
                                                      unsigned char& Yc, unsigned char& Uc, unsigned char& Vc) {
    float R = srgb_to_lin(R8 / 255.f);
    float G = srgb_to_lin(G8 / 255.f);
    float B = srgb_to_lin(B8 / 255.f);
    // BT.709 primaries
    float Y = 0.2126f * R + 0.7152f * G + 0.0722f * B;           // [0,1]
    float Cb = (B - Y) / 1.8556f;                                 // approx [-0.5,0.5]
    float Cr = (R - Y) / 1.5748f;                                 // approx [-0.5,0.5]
    int y  = (int)roundf(16.0f + 219.0f * Y);
    int cb = (int)roundf(128.0f + 224.0f * Cb);
    int cr = (int)roundf(128.0f + 224.0f * Cr);
    if (y < 16) y = 16; if (y > 235) y = 235;
    if (cb < 16) cb = 16; if (cb > 240) cb = 240;
    if (cr < 16) cr = 16; if (cr > 240) cr = 240;
    Yc = (unsigned char)y; Uc = (unsigned char)cb; Vc = (unsigned char)cr;
}

// Palette (B,G,R) similar to CPU overlay palette
__device__ __forceinline__ void palette_bgr_for_class(int cls, unsigned char& B, unsigned char& G, unsigned char& R) {
    const unsigned char pal[20][3] = {
        {255, 56, 56}, {255,157,151}, {255,112, 31}, {255,178, 29}, {207,210, 49},
        { 72,249, 10}, {146,204, 23}, { 61,219,134}, { 26,147, 52}, {  0,212,187},
        { 44,153,168}, {  0,194,255}, { 52, 69,147}, {100,115,255}, {  0, 24,236},
        {132, 56,255}, { 82,  0,133}, {203, 56,255}, {255,149,200}, {255, 55,199}
    };
    int i = cls % 20; if (i < 0) i += 20;
    B = pal[i][0]; G = pal[i][1]; R = pal[i][2];
}

// One block per box; single thread draws borders with simple loops
__global__ void k_draw_rects_nv12(uint8_t* y, int pitchY,
                                  uint8_t* uv, int pitchUV,
                                  int width, int height,
                                  const float* boxes_xyxy,
                                  const int* classes, int count,
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

    // Per-class color in YUV limited
    unsigned char B=0,G=0,R=0; palette_bgr_for_class(classes ? classes[i] : 0, B, G, R);
    unsigned char Yc=235, Uc=128, Vc=128;
    rgb_to_yuv709_limited(R, G, B, Yc, Uc, Vc);

    // Draw on Y plane
    for (int yy = y1; yy < y1 + t && yy < y2; ++yy) {
        uint8_t* row = y + yy * pitchY;
        for (int xx = x1; xx <= x2; ++xx) row[xx] = Yc;
    }
    for (int yy = max(y2 - t + 1, y1); yy <= y2; ++yy) {
        uint8_t* row = y + yy * pitchY;
        for (int xx = x1; xx <= x2; ++xx) row[xx] = Yc;
    }
    for (int xx = x1; xx < x1 + t && xx < x2; ++xx) {
        for (int yy = y1; yy <= y2; ++yy) {
            y[yy * pitchY + xx] = Yc;
        }
    }
    for (int xx = max(x2 - t + 1, x1); xx <= x2; ++xx) {
        for (int yy = y1; yy <= y2; ++yy) {
            y[yy * pitchY + xx] = Yc;
        }
    }

    // UV plane: set per-class U,V on border area
    const int uv_y1 = y1 / 2;
    const int uv_y2 = y2 / 2;
    const int uv_x1 = x1 / 2;
    const int uv_x2 = x2 / 2;
    const int ct = max(1, t/2);
    for (int uyy = uv_y1; uyy <= uv_y2; ++uyy) {
        uint8_t* row = uv + uyy * pitchUV;
        for (int uxx = uv_x1; uxx <= uv_x2; ++uxx) {
            if (uyy - uv_y1 < ct || uv_y2 - uyy < ct ||
                uxx - uv_x1 < ct || uv_x2 - uxx < ct) {
                row[uxx*2+0] = Uc; // NV12: U,V interleaved
                row[uxx*2+1] = Vc;
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
