#include "analyzer/cuda/preproc_letterbox_kernels.hpp"

namespace va::analyzer::cudaops {

__global__ void k_letterbox_bgr_to_nchw_fp32(
    const uint8_t* __restrict__ bgr,
    int in_w, int in_h,
    int out_w, int out_h,
    float* __restrict__ out,
    float scale, int pad_x, int pad_y,
    int nearest)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= out_w || y >= out_h) return;

    // target pixel corresponds to source coordinates
    int src_xi = (int)roundf((x - pad_x) / scale);
    int src_yi = (int)roundf((y - pad_y) / scale);

    float b=114.0f/255.0f, g=114.0f/255.0f, r=114.0f/255.0f;
    if (src_xi >= 0 && src_xi < in_w && src_yi >= 0 && src_yi < in_h) {
        int idx = (src_yi * in_w + src_xi) * 3;
        b = bgr[idx + 0] * (1.0f/255.0f);
        g = bgr[idx + 1] * (1.0f/255.0f);
        r = bgr[idx + 2] * (1.0f/255.0f);
    }

    // NCHW with channels: B(0), G(1), R(2) to match CPU path
    size_t plane = (size_t)out_w * (size_t)out_h;
    size_t pos = (size_t)y * (size_t)out_w + (size_t)x;
    out[pos] = b;
    out[plane + pos] = g;
    out[plane * 2 + pos] = r;
}

cudaError_t letterbox_bgr_to_nchw_fp32(
    const uint8_t* d_bgr,
    int in_w, int in_h,
    int out_w, int out_h,
    float* d_out,
    float scale, int pad_x, int pad_y,
    bool nearest,
    cudaStream_t stream)
{
    dim3 block(16, 16);
    dim3 grid((out_w + block.x - 1) / block.x,
              (out_h + block.y - 1) / block.y);
    k_letterbox_bgr_to_nchw_fp32<<<grid, block, 0, stream>>>(
        d_bgr, in_w, in_h, out_w, out_h, d_out, scale, pad_x, pad_y, nearest ? 1 : 0);
    return cudaGetLastError();
}

}

