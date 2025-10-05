#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"

namespace va::analyzer::cudaops {

// Stub: not implemented. Return error to trigger CPU fallback.
cudaError_t nms_yxyx_per_class(
    const float* /*d_boxes*/,
    const float* /*d_scores*/,
    const int32_t* /*d_classes*/,
    int /*num*/,
    float /*iou_threshold*/,
    int* /*d_keep*/,
    int* /*kept_count*/,
    cudaStream_t /*stream*/)
{
    return cudaErrorNotSupported;
}

}

