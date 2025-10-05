#include "analyzer/cuda/overlay_kernels.hpp"

namespace va::analyzer::cudaops {

__device__ inline void put_pixel(uint8_t* img, int w, int h, int x, int y, uint8_t b, uint8_t g, uint8_t r) {
    if (x < 0 || y < 0 || x >= w || y >= h) return;
    size_t idx = (static_cast<size_t>(y) * static_cast<size_t>(w) + static_cast<size_t>(x)) * 3ull;
    img[idx+0] = b; img[idx+1] = g; img[idx+2] = r;
}

__global__ void k_draw_rects(uint8_t* img, int w, int h, const float* boxes, const int32_t* classes, int n, int thick) {
    if (blockIdx.x != 0 || threadIdx.x != 0) return;
    for (int i=0;i<n;++i) {
        float x1f=boxes[i*4+0], y1f=boxes[i*4+1], x2f=boxes[i*4+2], y2f=boxes[i*4+3];
        int x1 = (int)roundf(x1f), y1=(int)roundf(y1f), x2=(int)roundf(x2f), y2=(int)roundf(y2f);
        // simple color by class
        int cls = classes? classes[i]:0;
        uint8_t r = (uint8_t)((37*cls + 97) % 255);
        uint8_t g = (uint8_t)((17*cls + 199) % 255);
        uint8_t b = (uint8_t)((233*cls + 53) % 255);
        for (int t=0;t<thick;++t) {
            // top/bottom
            for (int x=x1; x<=x2; ++x){ put_pixel(img,w,h,x,y1+t,b,g,r); put_pixel(img,w,h,x,y2-t,b,g,r);} 
            // left/right
            for (int y=y1; y<=y2; ++y){ put_pixel(img,w,h,x1+t,y,b,g,r); put_pixel(img,w,h,x2-t,y,b,g,r);} 
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
    dim3 grid(1), block(1);
    k_draw_rects<<<grid, block, 0, stream>>>(d_bgr, w, h, d_boxes, d_classes, num, thickness);
    return cudaGetLastError();
}

__global__ void k_fill_rects(uint8_t* img, int w, int h, const float* boxes, const int32_t* classes, int n, float alpha) {
    if (blockIdx.x != 0 || threadIdx.x != 0) return;
    if (alpha <= 0.0f) return;
    for (int i=0;i<n;++i) {
        float x1f=boxes[i*4+0], y1f=boxes[i*4+1], x2f=boxes[i*4+2], y2f=boxes[i*4+3];
        int x1 = (int)roundf(x1f), y1=(int)roundf(y1f), x2=(int)roundf(y2f>y1f?x2f:x1f), y2=(int)roundf(y2f);
        int cls = classes? classes[i]:0;
        uint8_t r = (uint8_t)((37*cls + 97) % 255);
        uint8_t g = (uint8_t)((17*cls + 199) % 255);
        uint8_t b = (uint8_t)((233*cls + 53) % 255);
        float a = fminf(fmaxf(alpha, 0.0f), 1.0f);
        for (int y=y1; y<=y2; ++y) {
            for (int x=x1; x<=x2; ++x) {
                if (x<0||y<0||x>=w||y>=h) continue;
                size_t idx = (static_cast<size_t>(y) * (size_t)w + (size_t)x) * 3ull;
                float cb = img[idx+0] * (1.0f - a) + b * a;
                float cg = img[idx+1] * (1.0f - a) + g * a;
                float cr = img[idx+2] * (1.0f - a) + r * a;
                img[idx+0] = (uint8_t)cb;
                img[idx+1] = (uint8_t)cg;
                img[idx+2] = (uint8_t)cr;
            }
        }
    }
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
    dim3 grid(1), block(1);
    k_fill_rects<<<grid, block, 0, stream>>>(d_bgr, w, h, d_boxes, d_classes, num, alpha);
    return cudaGetLastError();
}

}
