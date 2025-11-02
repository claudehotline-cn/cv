#pragma once

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(__CUDACC_RTC__)
#define VA_NV12KERN_CUDA 1
#endif

#include <cstdint>
#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

namespace va { namespace analyzer { namespace cudaops_nv12 {

// Draw rectangle borders on NV12 surface in-place (device memory).
// - y: pointer to Y plane (device)
// - pitchY: stride in bytes for Y plane
// - uv: pointer to interleaved UV plane (device)
// - pitchUV: stride in bytes for UV plane
// - width, height: frame size in pixels
// - boxes_xyxy: device pointer to N*4 floats [x1,y1,x2,y2,...]
// - classes: optional device pointer to N ints (can be nullptr); when provided, per-class colors are used for UV and Y
// - count: number of boxes
// - thickness: border thickness in pixels
// Returns cudaError_t (0 on success)
int draw_rects_nv12_inplace(uint8_t* y, int pitchY,
                            uint8_t* uv, int pitchUV,
                            int width, int height,
                            const float* boxes_xyxy,
                            const int* classes,
                            int count,
                            int thickness,
                            cudaStream_t stream = 0);

// Optional: filled rectangles with alpha; blends Y and UV (NV12 4:2:0 sampling)
int fill_rects_nv12_inplace(uint8_t* y, int pitchY,
                            uint8_t* uv, int pitchUV,
                            int width, int height,
                            const float* boxes_xyxy,
                            const int* classes,
                            int count,
                            float alpha /*0..1*/,
                            cudaStream_t stream = 0);

} } } // namespace
