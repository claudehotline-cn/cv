#pragma once

#include <cstdint>

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

namespace va::analyzer::cudaops {

// Draw rectangle borders (yxyx) on BGR image in device memory.
// d_bgr: device pointer to uint8_t image, row-major, 3 channels
// w,h: image size; stride = w*3 bytes
// d_boxes: [N,4] in pixel coords; d_classes: [N] class ids (for color selection)
// thickness: border thickness in pixels
cudaError_t draw_rects_bgr_inplace(
    uint8_t* d_bgr,
    int w,
    int h,
    const float* d_boxes,
    const int32_t* d_classes,
    int num,
    int thickness,
    cudaStream_t stream);

}

