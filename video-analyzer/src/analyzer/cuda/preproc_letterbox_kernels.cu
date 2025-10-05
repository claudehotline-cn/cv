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

__device__ inline void nv12_to_bgr(float Y, float U, float V, float& B, float& G, float& R) {
    // BT.601 approximate
    float C = Y - 16.0f;
    float D = U - 128.0f;
    float E = V - 128.0f;
    float r = 1.164f * C + 1.596f * E;
    float g = 1.164f * C - 0.392f * D - 0.813f * E;
    float b = 1.164f * C + 2.017f * D;
    // normalize to [0,1]
    R = fminf(fmaxf(r, 0.0f), 255.0f) * (1.0f/255.0f);
    G = fminf(fmaxf(g, 0.0f), 255.0f) * (1.0f/255.0f);
    B = fminf(fmaxf(b, 0.0f), 255.0f) * (1.0f/255.0f);
}

__global__ void k_letterbox_nv12_to_nchw_fp32(
    const uint8_t* __restrict__ y,
    int pitch_y,
    const uint8_t* __restrict__ uv,
    int pitch_uv,
    int in_w, int in_h,
    int out_w, int out_h,
    float* __restrict__ out,
    float scale, int pad_x, int pad_y,
    int nearest)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int yout = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= out_w || yout >= out_h) return;

    int src_xi = (int)roundf((x - pad_x) / scale);
    int src_yi = (int)roundf((yout - pad_y) / scale);

    float B=114.0f/255.0f, G=114.0f/255.0f, R=114.0f/255.0f;
    if (src_xi >= 0 && src_xi < in_w && src_yi >= 0 && src_yi < in_h) {
        // luma
        uint8_t Yv = y[src_yi * pitch_y + src_xi];
        // chroma (NV12 interleaved UV, subsampled 2x2)
        int uvi = (src_yi / 2) * pitch_uv + (src_xi / 2) * 2;
        uint8_t Uv = uv[uvi + 0];
        uint8_t Vv = uv[uvi + 1];
        nv12_to_bgr((float)Yv, (float)Uv, (float)Vv, B, G, R);
    }

    size_t plane = (size_t)out_w * (size_t)out_h;
    size_t pos = (size_t)yout * (size_t)out_w + (size_t)x;
    out[pos] = B;
    out[plane + pos] = G;
    out[plane * 2 + pos] = R;
}

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
    cudaStream_t stream)
{
    dim3 block(16, 16);
    dim3 grid((out_w + block.x - 1) / block.x,
              (out_h + block.y - 1) / block.y);
    k_letterbox_nv12_to_nchw_fp32<<<grid, block, 0, stream>>>(
        d_y, pitch_y, d_uv, pitch_uv,
        in_w, in_h,
        out_w, out_h,
        d_out, scale, pad_x, pad_y, nearest ? 1 : 0);
    return cudaGetLastError();
}

}
