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

    float b=114.0f/255.0f, g=114.0f/255.0f, r=114.0f/255.0f;
    // Map target pixel center到源坐标系
    float src_x = ((float)x - (float)pad_x + 0.5f) / scale - 0.5f;
    float src_y = ((float)y - (float)pad_y + 0.5f) / scale - 0.5f;

    if (nearest) {
        int src_xi = (int)roundf(src_x);
        int src_yi = (int)roundf(src_y);
        if (src_xi >= 0 && src_xi < in_w && src_yi >= 0 && src_yi < in_h) {
            int idx = (src_yi * in_w + src_xi) * 3;
            b = bgr[idx + 0] * (1.0f/255.0f);
            g = bgr[idx + 1] * (1.0f/255.0f);
            r = bgr[idx + 2] * (1.0f/255.0f);
        }
    } else {
        // 简单双线性采样，与 CPU 路径更接近
        if (src_x >= 0.0f && src_x <= (float)(in_w - 1) &&
            src_y >= 0.0f && src_y <= (float)(in_h - 1)) {
            int x0 = (int)floorf(src_x);
            int y0 = (int)floorf(src_y);
            int x1 = x0 + 1;
            int y1 = y0 + 1;
            if (x1 >= in_w) x1 = in_w - 1;
            if (y1 >= in_h) y1 = in_h - 1;
            float fx = src_x - (float)x0;
            float fy = src_y - (float)y0;

            auto sample = [&](int sx, int sy, float& sb, float& sg, float& sr) {
                int idx = (sy * in_w + sx) * 3;
                sb = bgr[idx + 0] * (1.0f/255.0f);
                sg = bgr[idx + 1] * (1.0f/255.0f);
                sr = bgr[idx + 2] * (1.0f/255.0f);
            };

            float b00, g00, r00;
            float b10, g10, r10;
            float b01, g01, r01;
            float b11, g11, r11;
            sample(x0, y0, b00, g00, r00);
            sample(x1, y0, b10, g10, r10);
            sample(x0, y1, b01, g01, r01);
            sample(x1, y1, b11, g11, r11);

            float w00 = (1.0f - fx) * (1.0f - fy);
            float w10 = fx * (1.0f - fy);
            float w01 = (1.0f - fx) * fy;
            float w11 = fx * fy;

            b = w00*b00 + w10*b10 + w01*b01 + w11*b11;
            g = w00*g00 + w10*g10 + w01*g01 + w11*g11;
            r = w00*r00 + w10*r10 + w01*r01 + w11*r11;
        }
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

    float B=114.0f/255.0f, G=114.0f/255.0f, R=114.0f/255.0f;
    // Map target pixel center到源坐标系
    float src_x = ((float)x - (float)pad_x + 0.5f) / scale - 0.5f;
    float src_y = ((float)yout - (float)pad_y + 0.5f) / scale - 0.5f;

    if (nearest) {
        int src_xi = (int)roundf(src_x);
        int src_yi = (int)roundf(src_y);
        if (src_xi >= 0 && src_xi < in_w && src_yi >= 0 && src_yi < in_h) {
            // luma
            uint8_t Yv = y[src_yi * pitch_y + src_xi];
            // chroma (NV12 interleaved UV, subsampled 2x2)
            int uvi = (src_yi / 2) * pitch_uv + (src_xi / 2) * 2;
            uint8_t Uv = uv[uvi + 0];
            uint8_t Vv = uv[uvi + 1];
            nv12_to_bgr((float)Yv, (float)Uv, (float)Vv, B, G, R);
        }
    } else {
        // 双线性采样 NV12：Y 在 full-res 上插值，UV 在 subsampled 网格上插值
        if (src_x >= 0.0f && src_x <= (float)(in_w - 1) &&
            src_y >= 0.0f && src_y <= (float)(in_h - 1)) {
            int x0 = (int)floorf(src_x);
            int y0 = (int)floorf(src_y);
            int x1 = x0 + 1;
            int y1 = y0 + 1;
            if (x1 >= in_w) x1 = in_w - 1;
            if (y1 >= in_h) y1 = in_h - 1;
            float fx = src_x - (float)x0;
            float fy = src_y - (float)y0;

            auto sampleY = [&](int sx, int sy)->float {
                return (float)y[sy * pitch_y + sx];
            };

            float Y00 = sampleY(x0, y0);
            float Y10 = sampleY(x1, y0);
            float Y01 = sampleY(x0, y1);
            float Y11 = sampleY(x1, y1);

            float w00 = (1.0f - fx) * (1.0f - fy);
            float w10 = fx * (1.0f - fy);
            float w01 = (1.0f - fx) * fy;
            float w11 = fx * fy;

            float Yv = w00*Y00 + w10*Y10 + w01*Y01 + w11*Y11;

            int cw = in_w / 2;
            int ch = in_h / 2;
            float cx = src_x * 0.5f;
            float cy = src_y * 0.5f;
            if (cw > 0 && ch > 0) {
                // clamp chroma coords到有效范围
                if (cx < 0.0f) cx = 0.0f;
                if (cy < 0.0f) cy = 0.0f;
                if (cx > (float)(cw - 1)) cx = (float)(cw - 1);
                if (cy > (float)(ch - 1)) cy = (float)(ch - 1);
                int cx0 = (int)floorf(cx);
                int cy0 = (int)floorf(cy);
                int cx1 = cx0 + 1;
                int cy1 = cy0 + 1;
                if (cx1 >= cw) cx1 = cw - 1;
                if (cy1 >= ch) cy1 = ch - 1;
                float fx_c = cx - (float)cx0;
                float fy_c = cy - (float)cy0;

                auto sampleUV = [&](int sx, int sy, float& U, float& V) {
                    int uvi = sy * pitch_uv + sx * 2;
                    U = (float)uv[uvi + 0];
                    V = (float)uv[uvi + 1];
                };

                float U00, V00;
                float U10, V10;
                float U01, V01;
                float U11, V11;
                sampleUV(cx0, cy0, U00, V00);
                sampleUV(cx1, cy0, U10, V10);
                sampleUV(cx0, cy1, U01, V01);
                sampleUV(cx1, cy1, U11, V11);

                float Uv = w00*U00 + w10*U10 + w01*U01 + w11*U11;
                float Vv = w00*V00 + w10*V10 + w01*V01 + w11*V11;

                nv12_to_bgr(Yv, Uv, Vv, B, G, R);
            }
        }
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
