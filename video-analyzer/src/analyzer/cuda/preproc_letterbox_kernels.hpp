#pragma once

#include <cstdint>

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

namespace va::analyzer::cudaops {

// Launches a CUDA kernel that writes letterboxed BGR->NCHW FP32 output on device.
// - d_bgr: device pointer to input BGR (uint8_t, HxWx3, continuous)
// - in_w/in_h: input dimensions; in_stride_bytes = in_w * 3
// - out_w/out_h: output (letterboxed) dimensions
// - d_out: device pointer to output float tensor (1x3xHoutxWout)
// - scale/pad_x/pad_y: computed on host according to letterbox rules
// - nearest: if true, use nearest sampling; else simple bilinear (optional)
// Returns cudaError_t; caller should check for cudaSuccess
cudaError_t letterbox_bgr_to_nchw_fp32(
    const uint8_t* d_bgr,
    int in_w, int in_h,
    int out_w, int out_h,
    float* d_out,
    float scale, int pad_x, int pad_y,
    bool nearest,
    cudaStream_t stream);

// Launches a CUDA kernel that writes letterboxed NV12->NCHW FP32 output on device.
// - d_y: device pointer to Y plane, pitch_y bytes per row
// - d_uv: device pointer to interleaved UV plane, pitch_uv bytes per row
// - in_w/in_h: input luma dimensions
// - out_w/out_h: output (letterboxed) dimensions
// - d_out: device pointer to output float tensor (1x3xHoutxWout), BGR order [0..1]
// - scale/pad_x/pad_y: letterbox parameters
cudaError_t letterbox_nv12_to_nchw_fp32(
    const uint8_t* d_y,
    int pitch_y,
    const uint8_t* d_uv,
    int pitch_uv,
    int in_w, int in_h,
    int out_w, int out_h,
    float* d_out,
    float scale, int pad_x, int pad_y,
    bool nearest,
    cudaStream_t stream);

}
