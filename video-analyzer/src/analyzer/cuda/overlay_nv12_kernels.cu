#include "analyzer/cuda/overlay_nv12_kernels.hpp"

#include <cuda_runtime.h>
#include <math.h>

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

// Signed distance for rounded rectangle
__device__ __forceinline__ float sdRoundRect(float2 p, float2 b, float r) {
    float2 q = make_float2(fabsf(p.x) - b.x + r, fabsf(p.y) - b.y + r);
    float outside = hypotf(fmaxf(q.x, 0.f), fmaxf(q.y, 0.f)) - r;
    float inside  = fminf(fmaxf(q.x, q.y), 0.f);
    return outside + inside; // <0 inside; ~=0 edge; >0 outside
}

// Y fill pass with AA rounded rects
__global__ void k_fill_Y_nv12(uint8_t* Y, int pitchY,
                              int width, int height,
                              const float* boxes_xyxy,
                              const int* classes, int nBoxes,
                              float fillAlpha)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;
    unsigned char* row = Y + y * pitchY;
    float Ydst = (float)row[x];
    float accumA = 0.f, accumY = 0.f;
    for (int i = 0; i < nBoxes; ++i) {
        float x1 = boxes_xyxy[i*4+0];
        float y1 = boxes_xyxy[i*4+1];
        float x2 = boxes_xyxy[i*4+2];
        float y2 = boxes_xyxy[i*4+3];
        if (x < (int)floorf(x1) - 2 || x > (int)ceilf(x2) + 2 ||
            y < (int)floorf(y1) - 2 || y > (int)ceilf(y2) + 2) continue;
        float2 c = make_float2(0.5f*(x1+x2), 0.5f*(y1+y2));
        float2 p = make_float2(x - c.x, y - c.y);
        float2 half = make_float2(0.5f*(x2-x1), 0.5f*(y2-y1));
        float radius = fminf(half.x, half.y) * 0.10f; // 10% rounded corners
        float d = sdRoundRect(p, half, radius);
        float aFill = 0.f;
        if (fillAlpha > 0.f) {
            float t = -d; // inside positive
            aFill = fminf(1.f, fmaxf(0.f, t + 0.5f)) * fillAlpha;
        }
        if (aFill <= 0.f) continue;
        unsigned char B=0,G=0,R=0; palette_bgr_for_class(classes?classes[i]:0, B,G,R);
        unsigned char Yc=200, Uc=128, Vc=128; rgb_to_yuv709_limited(R,G,B,Yc,Uc,Vc);
        accumY += aFill * (float)Yc;
        accumA += aFill;
    }
    if (accumA > 0.f) {
        float a = fminf(1.f, accumA);
        float Ysrc = accumY / accumA;
        float Yout = Ysrc * a + Ydst * (1.f - a);
        if (Yout < 16.f) Yout = 16.f; if (Yout > 235.f) Yout = 235.f;
        row[x] = (unsigned char)(Yout + 0.5f);
    }
}

// Y stroke pass with AA rounded rects
__global__ void k_stroke_Y_nv12(uint8_t* Y, int pitchY,
                                int width, int height,
                                const float* boxes_xyxy,
                                const int* classes, int nBoxes,
                                int thickness)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= width || y >= height) return;
    unsigned char* row = Y + y * pitchY;
    float Ydst = (float)row[x];
    float accumA = 0.f, accumY = 0.f;
    for (int i = 0; i < nBoxes; ++i) {
        float x1 = boxes_xyxy[i*4+0];
        float y1 = boxes_xyxy[i*4+1];
        float x2 = boxes_xyxy[i*4+2];
        float y2 = boxes_xyxy[i*4+3];
        if (x < (int)floorf(x1) - thickness - 2 || x > (int)ceilf(x2) + thickness + 2 ||
            y < (int)floorf(y1) - thickness - 2 || y > (int)ceilf(y2) + thickness + 2) continue;
        float2 c = make_float2(0.5f*(x1+x2), 0.5f*(y1+y2));
        float2 p = make_float2(x - c.x, y - c.y);
        float2 half = make_float2(0.5f*(x2-x1), 0.5f*(y2-y1));
        float radius = fminf(half.x, half.y) * 0.10f;
        float d = sdRoundRect(p, half, radius);
        float aStroke = 0.f;
        if (thickness > 0) {
            float ad = fabsf(d);
            float edge = fabsf(ad - 0.5f * thickness);
            float aa = 1.f - fminf(1.f, fmaxf(0.f, edge - 0.5f));
            float ring = fminf(1.f, fmaxf(0.f, (0.5f*thickness + 0.5f) - ad)) *
                         fminf(1.f, fmaxf(0.f, ad - (0.5f*thickness - 0.5f)));
            aStroke = aa * ring; // strokeAlpha assumed 1.0
        }
        if (aStroke <= 0.f) continue;
        unsigned char B=0,G=0,R=0; palette_bgr_for_class(classes?classes[i]:0, B,G,R);
        unsigned char Yc=235, Uc=128, Vc=128; rgb_to_yuv709_limited(R,G,B,Yc,Uc,Vc);
        accumY += aStroke * (float)Yc;
        accumA += aStroke;
    }
    if (accumA > 0.f) {
        float a = fminf(1.f, accumA);
        float Ysrc = accumY / accumA;
        float Yout = Ysrc * a + Ydst * (1.f - a);
        if (Yout < 16.f) Yout = 16.f; if (Yout > 235.f) Yout = 235.f;
        row[x] = (unsigned char)(Yout + 0.5f);
    }
}

// UV fill pass (process one UV sample per thread; average coverage over 2x2 Y)
__global__ void k_fill_UV_nv12(uint8_t* UV, int pitchUV,
                               int width, int height,
                               const float* boxes_xyxy,
                               const int* classes, int nBoxes,
                               float fillAlpha)
{
    int ux = blockIdx.x * blockDim.x + threadIdx.x;
    int uy = blockIdx.y * blockDim.y + threadIdx.y;
    if (ux >= width/2 || uy >= height/2) return;
    int x0 = ux * 2, y0 = uy * 2;
    float accumU = 0.f, accumV = 0.f, accumA = 0.f;
    for (int oy = 0; oy < 2; ++oy)
    for (int ox = 0; ox < 2; ++ox) {
        int x = x0 + ox, y = y0 + oy;
        for (int i = 0; i < nBoxes; ++i) {
            float x1 = boxes_xyxy[i*4+0];
            float y1 = boxes_xyxy[i*4+1];
            float x2 = boxes_xyxy[i*4+2];
            float y2 = boxes_xyxy[i*4+3];
            if (x < (int)floorf(x1) - 2 || x > (int)ceilf(x2) + 2 ||
                y < (int)floorf(y1) - 2 || y > (int)ceilf(y2) + 2) continue;
            float2 c = make_float2(0.5f*(x1+x2), 0.5f*(y1+y2));
            float2 p = make_float2(x - c.x, y - c.y);
            float2 half = make_float2(0.5f*(x2-x1), 0.5f*(y2-y1));
            float radius = fminf(half.x, half.y) * 0.10f;
            float d = sdRoundRect(p, half, radius);
            float aFill = 0.f;
            if (fillAlpha > 0.f) {
                float t = -d;
                aFill = fminf(1.f, fmaxf(0.f, t + 0.5f)) * fillAlpha;
            }
            if (aFill > 0.f) {
                unsigned char B=0,G=0,R=0; palette_bgr_for_class(classes?classes[i]:0, B,G,R);
                unsigned char Yc, Uc, Vc; rgb_to_yuv709_limited(R,G,B,Yc,Uc,Vc);
                accumU += aFill * (float)Uc;
                accumV += aFill * (float)Vc;
                accumA += aFill;
            }
        }
    }
    unsigned char* row = UV + uy * pitchUV;
    unsigned char U0 = row[ux*2+0];
    unsigned char V0 = row[ux*2+1];
    if (accumA > 0.f) {
        float a = fminf(1.f, accumA / 4.f);
        float Usrc = accumU / accumA;
        float Vsrc = accumV / accumA;
        float Uout = Usrc * a + (float)U0 * (1.f - a);
        float Vout = Vsrc * a + (float)V0 * (1.f - a);
        if (Uout < 16.f) Uout = 16.f; if (Uout > 240.f) Uout = 240.f;
        if (Vout < 16.f) Vout = 16.f; if (Vout > 240.f) Vout = 240.f;
        row[ux*2+0] = (unsigned char)(Uout + 0.5f);
        row[ux*2+1] = (unsigned char)(Vout + 0.5f);
    }
}

// UV stroke pass (2x2 average like fill)
__global__ void k_stroke_UV_nv12(uint8_t* UV, int pitchUV,
                                 int width, int height,
                                 const float* boxes_xyxy,
                                 const int* classes, int nBoxes,
                                 int thickness)
{
    int ux = blockIdx.x * blockDim.x + threadIdx.x;
    int uy = blockIdx.y * blockDim.y + threadIdx.y;
    if (ux >= width/2 || uy >= height/2) return;
    int x0 = ux * 2, y0 = uy * 2;
    float accumU = 0.f, accumV = 0.f, accumA = 0.f;
    for (int oy = 0; oy < 2; ++oy)
    for (int ox = 0; ox < 2; ++ox) {
        int x = x0 + ox, y = y0 + oy;
        for (int i = 0; i < nBoxes; ++i) {
            float x1 = boxes_xyxy[i*4+0];
            float y1 = boxes_xyxy[i*4+1];
            float x2 = boxes_xyxy[i*4+2];
            float y2 = boxes_xyxy[i*4+3];
            if (x < (int)floorf(x1) - thickness - 2 || x > (int)ceilf(x2) + thickness + 2 ||
                y < (int)floorf(y1) - thickness - 2 || y > (int)ceilf(y2) + thickness + 2) continue;
            float2 c = make_float2(0.5f*(x1+x2), 0.5f*(y1+y2));
            float2 p = make_float2(x - c.x, y - c.y);
            float2 half = make_float2(0.5f*(x2-x1), 0.5f*(y2-y1));
            float radius = fminf(half.x, half.y) * 0.10f;
            float d = sdRoundRect(p, half, radius);
            float aStroke = 0.f;
            if (thickness > 0) {
                float ad = fabsf(d);
                float edge = fabsf(ad - 0.5f * thickness);
                float aa = 1.f - fminf(1.f, fmaxf(0.f, edge - 0.5f));
                float ring = fminf(1.f, fmaxf(0.f, (0.5f*thickness + 0.5f) - ad)) *
                             fminf(1.f, fmaxf(0.f, ad - (0.5f*thickness - 0.5f)));
                aStroke = aa * ring;
            }
            if (aStroke > 0.f) {
                unsigned char B=0,G=0,R=0; palette_bgr_for_class(classes?classes[i]:0, B,G,R);
                unsigned char Yc, Uc, Vc; rgb_to_yuv709_limited(R,G,B,Yc,Uc,Vc);
                accumU += aStroke * (float)Uc;
                accumV += aStroke * (float)Vc;
                accumA += aStroke;
            }
        }
    }
    unsigned char* row = UV + uy * pitchUV;
    unsigned char U0 = row[ux*2+0];
    unsigned char V0 = row[ux*2+1];
    if (accumA > 0.f) {
        float a = fminf(1.f, accumA / 4.f);
        float Usrc = accumU / accumA;
        float Vsrc = accumV / accumA;
        float Uout = Usrc * a + (float)U0 * (1.f - a);
        float Vout = Vsrc * a + (float)V0 * (1.f - a);
        if (Uout < 16.f) Uout = 16.f; if (Uout > 240.f) Uout = 240.f;
        if (Vout < 16.f) Vout = 16.f; if (Vout > 240.f) Vout = 240.f;
        row[ux*2+0] = (unsigned char)(Uout + 0.5f);
        row[ux*2+1] = (unsigned char)(Vout + 0.5f);
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
    dim3 blk(32, 8);
    dim3 grdY((width + blk.x - 1)/blk.x, (height + blk.y - 1)/blk.y);
    k_stroke_Y_nv12<<<grdY, blk>>>(y, pitchY, width, height, boxes_xyxy, classes, count, thickness);
    cudaError_t e1 = cudaGetLastError();
    dim3 grdUV(((width/2) + blk.x - 1)/blk.x, ((height/2) + blk.y - 1)/blk.y);
    k_stroke_UV_nv12<<<grdUV, blk>>>(uv, pitchUV, width, height, boxes_xyxy, classes, count, thickness);
    cudaError_t e2 = cudaGetLastError();
    return (int)(e1 != cudaSuccess ? e1 : e2);
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
                            uint8_t* uv, int pitchUV,
                            int width, int height,
                            const float* boxes_xyxy,
                            const int* classes,
                            int count,
                            float alpha)
{
    if (!y || !uv || !boxes_xyxy || count <= 0 || width<=0 || height<=0) return cudaErrorInvalidValue;
    dim3 blk(32, 8);
    dim3 grdY((width + blk.x - 1)/blk.x, (height + blk.y - 1)/blk.y);
    k_fill_Y_nv12<<<grdY, blk>>>(y, pitchY, width, height, boxes_xyxy, classes, count, alpha);
    cudaError_t e1 = cudaGetLastError();
    dim3 grdUV(((width/2) + blk.x - 1)/blk.x, ((height/2) + blk.y - 1)/blk.y);
    k_fill_UV_nv12<<<grdUV, blk>>>(uv, pitchUV, width, height, boxes_xyxy, classes, count, alpha);
    cudaError_t e2 = cudaGetLastError();
    return (int)(e1 != cudaSuccess ? e1 : e2);
}

} } } // namespace
