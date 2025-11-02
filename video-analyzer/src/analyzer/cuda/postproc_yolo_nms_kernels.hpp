#pragma once

#include <cstddef>
#include <cstdint>

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

namespace va::analyzer::cudaops {

// Very small placeholder for CUDA NMS; real implementation should sort by score
// and compute IoU in parallel. Here we only provide a signature and return error
// when kernels are not compiled.
// boxes: [N, 4] (x1,y1,x2,y2)
// scores: [N]
// classes: [N]
// keep: output indices to keep (device array of size N); returns number kept via host param kept_out.
cudaError_t nms_yxyx_per_class(
    const float* d_boxes,
    const float* d_scores,
    const int32_t* d_classes,
    int num,
    float iou_threshold,
    int* d_keep,
    int* kept_count,
    cudaStream_t stream);

}

