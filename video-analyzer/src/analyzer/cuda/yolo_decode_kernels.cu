#include "analyzer/cuda/yolo_decode_kernels.hpp"
#if defined(__CUDACC__) || defined(USE_CUDA)
#include <cuda_fp16.h>
#endif

namespace va::analyzer::cudaops {
// NOTE: ensure this TU always compiles fp16 helpers; minor edit to force rebuild

__global__ void k_yolo_decode(
    const float* out, int N, int A, int K, int ch_first, float conf_thr,
    float pre_sx, float pre_sy,
    float scale, int pad_x, int pad_y, int ow, int oh,
    float* boxes, float* scores, int32_t* classes, int* count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    auto at = [&](int attr)->float { return ch_first ? out[attr * N + i] : out[i * A + attr]; };
    float cx = at(0) * pre_sx, cy = at(1) * pre_sy, w = at(2) * pre_sx, h = at(3) * pre_sy;
    float best=0.0f; int bc=-1;
    for (int c=0;c<K;++c){ float s=at(4+c); if (s>best){ best=s; bc=c; } }
    if (bc<0 || best<conf_thr) return;
    float x1 = cx - 0.5f*w, y1 = cy - 0.5f*h, x2 = cx + 0.5f*w, y2 = cy + 0.5f*h;
    float invs = (scale==0.0f ? 1.0f : scale);
    float ox1 = (x1 - pad_x) / invs;
    float oy1 = (y1 - pad_y) / invs;
    float ox2 = (x2 - pad_x) / invs;
    float oy2 = (y2 - pad_y) / invs;
    ox1 = fminf(fmaxf(0.0f, ox1), ow-1.0f);
    oy1 = fminf(fmaxf(0.0f, oy1), oh-1.0f);
    ox2 = fminf(fmaxf(0.0f, ox2), ow-1.0f);
    oy2 = fminf(fmaxf(0.0f, oy2), oh-1.0f);
    if (ox2<=ox1 || oy2<=oy1) return;
    int idx = atomicAdd(count, 1);
    boxes[idx*4+0]=ox1; boxes[idx*4+1]=oy1; boxes[idx*4+2]=ox2; boxes[idx*4+3]=oy2;
    scores[idx]=best; classes[idx]=bc;
}

cudaError_t yolo_decode_to_yxyx(
    const float* d_out,
    int num_det,
    int num_attrs,
    int num_classes,
    int channels_first,
    float conf_thr,
    float pre_sx,
    float pre_sy,
    float scale,
    int pad_x,
    int pad_y,
    int orig_w,
    int orig_h,
    float* d_boxes,
    float* d_scores,
    int32_t* d_classes,
    int* d_count,
    cudaStream_t stream)
{
    int threads = 256;
    int blocks = (num_det + threads - 1) / threads;
    k_yolo_decode<<<blocks, threads, 0, stream>>>(d_out, num_det, num_attrs, num_classes, channels_first, conf_thr,
        pre_sx, pre_sy, scale, pad_x, pad_y, orig_w, orig_h, d_boxes, d_scores, d_classes, d_count);
    return cudaGetLastError();
}

#if defined(__CUDACC__) || defined(USE_CUDA)
// FP16 输入（__half）版本：逻辑与 float 版本一致，仅将读取转为 __half2float
__global__ void k_yolo_decode_fp16(
    const __half* out, int N, int A, int K, int ch_first, float conf_thr,
    float pre_sx, float pre_sy,
    float scale, int pad_x, int pad_y, int ow, int oh,
    float* boxes, float* scores, int32_t* classes, int* count)
{
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= N) return;
    auto at = [&](int attr)->float { __half h = (ch_first ? out[attr * N + i] : out[i * A + attr]); return __half2float(h); };
    float cx = at(0) * pre_sx, cy = at(1) * pre_sy, w = at(2) * pre_sx, h = at(3) * pre_sy;
    float best=0.0f; int bc=-1;
    for (int c=0;c<K;++c){ float s=at(4+c); if (s>best){ best=s; bc=c; } }
    if (bc<0 || best<conf_thr) return;
    float x1 = cx - 0.5f*w, y1 = cy - 0.5f*h, x2 = cx + 0.5f*w, y2 = cy + 0.5f*h;
    float invs = (scale==0.0f ? 1.0f : scale);
    float ox1 = (x1 - pad_x) / invs;
    float oy1 = (y1 - pad_y) / invs;
    float ox2 = (x2 - pad_x) / invs;
    float oy2 = (y2 - pad_y) / invs;
    ox1 = fminf(fmaxf(0.0f, ox1), ow-1.0f);
    oy1 = fminf(fmaxf(0.0f, oy1), oh-1.0f);
    ox2 = fminf(fmaxf(0.0f, ox2), ow-1.0f);
    oy2 = fminf(fmaxf(0.0f, oy2), oh-1.0f);
    if (ox2<=ox1 || oy2<=oy1) return;
    int idx = ::atomicAdd(count, 1);
    boxes[idx*4+0]=ox1; boxes[idx*4+1]=oy1; boxes[idx*4+2]=ox2; boxes[idx*4+3]=oy2;
    scores[idx]=best; classes[idx]=bc;
}

cudaError_t yolo_decode_to_yxyx_fp16(
    const __half* d_out,
    int num_det,
    int num_attrs,
    int num_classes,
    int channels_first,
    float conf_thr,
    float pre_sx,
    float pre_sy,
    float scale,
    int pad_x,
    int pad_y,
    int orig_w,
    int orig_h,
    float* d_boxes,
    float* d_scores,
    int32_t* d_classes,
    int* d_count,
    cudaStream_t stream)
{
    int threads = 256;
    int blocks = (num_det + threads - 1) / threads;
    k_yolo_decode_fp16<<<blocks, threads, 0, stream>>>(d_out, num_det, num_attrs, num_classes, channels_first, conf_thr,
        pre_sx, pre_sy, scale, pad_x, pad_y, orig_w, orig_h, d_boxes, d_scores, d_classes, d_count);
    return cudaGetLastError();
}

__global__ void k_half_to_float(const __half* in, float* out, int n) {
    int i = blockIdx.x * blockDim.x + threadIdx.x;
    if (i < n) out[i] = __half2float(in[i]);
}

cudaError_t half_to_float(const __half* d_in, float* d_out, int n, cudaStream_t stream) {
    int threads = 256;
    int blocks = (n + threads - 1) / threads;
    k_half_to_float<<<blocks, threads, 0, stream>>>(d_in, d_out, n);
    return cudaGetLastError();
}
#endif

}
