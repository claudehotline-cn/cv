#pragma once

#include <cstdint>

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

namespace va::analyzer::cudaops {

// Decodes YOLO output tensor (1 x N x (4+K) or 1 x (4+K) x N) into per-detection arrays on device.
// Inputs:
//   d_out: device pointer to model output float tensor (assumed contiguous)
//   num_det, num_attrs, num_classes: tensor layout params
//   channels_first: if true, layout is [C,N], else [N,C]
//   conf_thr: score threshold
//   letterbox meta: scale/pad and original size for mapping back
// Outputs:
//   d_boxes: device float array [M,4] (yxyx) (pre-allocated for num_det)
//   d_scores: device float array [M]
//   d_classes: device int32 array [M]
//   d_count: device int, number of written detections (<= num_det)
// Returns cudaError_t
cudaError_t yolo_decode_to_yxyx(
    const float* d_out,
    int num_det,
    int num_attrs,
    int num_classes,
    int channels_first,
    float conf_thr,
    float scale,
    int pad_x,
    int pad_y,
    int orig_w,
    int orig_h,
    float* d_boxes,
    float* d_scores,
    int32_t* d_classes,
    int* d_count,
    cudaStream_t stream);

}

