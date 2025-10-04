#include <cuda_runtime.h>

extern "C" __global__ void nv12_to_rgb_planar_kernel(const unsigned char* __restrict__ y_plane,
                                                     const unsigned char* __restrict__ uv_plane,
                                                     int width,
                                                     int height,
                                                     int pitch_y,
                                                     int pitch_uv,
                                                     float* __restrict__ dst)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;

    if (x >= width || y >= height) {
        return;
    }

    int y_index = y * pitch_y + x;
    int uv_x = x / 2;
    int uv_y = y / 2;
    int uv_index = uv_y * pitch_uv + uv_x * 2;

    float Y = static_cast<float>(y_plane[y_index]);
    float U = static_cast<float>(uv_plane[uv_index]) - 128.0f;
    float V = static_cast<float>(uv_plane[uv_index + 1]) - 128.0f;

    float R = Y + 1.402f * V;
    float G = Y - 0.344136f * U - 0.714136f * V;
    float B = Y + 1.772f * U;

    R = fminf(fmaxf(R, 0.0f), 255.0f) / 255.0f;
    G = fminf(fmaxf(G, 0.0f), 255.0f) / 255.0f;
    B = fminf(fmaxf(B, 0.0f), 255.0f) / 255.0f;

    const int plane_size = width * height;
    const int idx = y * width + x;

    dst[idx] = R;
    dst[idx + plane_size] = G;
    dst[idx + 2 * plane_size] = B;
}
extern "C" __global__ void letterbox_resize_kernel(const float* __restrict__ src,
                                                    int src_width,
                                                    int src_height,
                                                    float* __restrict__ dst,
                                                    int dst_width,
                                                    int dst_height,
                                                    float scale,
                                                    int pad_x,
                                                    int pad_y)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;

    if (x >= dst_width || y >= dst_height) {
        return;
    }

    float src_x = (static_cast<float>(x - pad_x) + 0.5f) / scale - 0.5f;
    float src_y = (static_cast<float>(y - pad_y) + 0.5f) / scale - 0.5f;

    int ix = static_cast<int>(floorf(src_x));
    int iy = static_cast<int>(floorf(src_y));

    const int plane_size = src_width * src_height;
    const int dst_plane_size = dst_width * dst_height;
    const int idx = y * dst_width + x;

    if (ix >= 0 && iy >= 0 && ix < src_width && iy < src_height) {
        const int src_idx = iy * src_width + ix;
        dst[idx] = src[src_idx];
        dst[idx + dst_plane_size] = src[src_idx + plane_size];
        dst[idx + 2 * dst_plane_size] = src[src_idx + 2 * plane_size];
    } else {
        dst[idx] = 114.0f / 255.0f;
        dst[idx + dst_plane_size] = 114.0f / 255.0f;
        dst[idx + 2 * dst_plane_size] = 114.0f / 255.0f;
    }
}
