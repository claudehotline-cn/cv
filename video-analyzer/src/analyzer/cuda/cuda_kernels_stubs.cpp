// CPU build/link stubs for CUDA kernels when NVCC kernels are not compiled.
// These satisfy linker references from postproc_yolo_det.cpp when VA_HAS_CUDA_KERNELS is not defined.

#include "analyzer/cuda/yolo_decode_kernels.hpp"
#include "analyzer/cuda/postproc_yolo_nms_kernels.hpp"

#if defined(USE_CUDA)
#include <cuda_runtime_api.h>
#endif

namespace va::analyzer::cudaops {

#if !defined(VA_HAS_CUDA_KERNELS)

cudaError_t yolo_decode_to_yxyx(
    const float* /*d_out*/,
    int /*num_det*/,
    int /*num_attrs*/,
    int /*num_classes*/,
    int /*channels_first*/,
    float /*conf_thr*/,
    float /*pre_sx*/,
    float /*pre_sy*/,
    float /*scale*/,
    int /*pad_x*/,
    int /*pad_y*/,
    int /*orig_w*/,
    int /*orig_h*/,
    float* /*d_boxes*/,
    float* /*d_scores*/,
    int32_t* /*d_classes*/,
    int* d_count,
    cudaStream_t /*stream*/) {
#if defined(USE_CUDA)
    if (d_count) *d_count = 0;
    return cudaErrorNotSupported;
#else
    if (d_count) *d_count = 0;
    return (cudaError_t)0; // placeholder when cuda headers absent
#endif
}

cudaError_t yolo_decode_to_yxyx_fp16(
    const __half* /*d_out*/,
    int /*num_det*/,
    int /*num_attrs*/,
    int /*num_classes*/,
    int /*channels_first*/,
    float /*conf_thr*/,
    float /*pre_sx*/,
    float /*pre_sy*/,
    float /*scale*/,
    int /*pad_x*/,
    int /*pad_y*/,
    int /*orig_w*/,
    int /*orig_h*/,
    float* /*d_boxes*/,
    float* /*d_scores*/,
    int32_t* /*d_classes*/,
    int* d_count,
    cudaStream_t /*stream*/) {
#if defined(USE_CUDA)
    if (d_count) *d_count = 0;
    return cudaErrorNotSupported;
#else
    if (d_count) *d_count = 0;
    return (cudaError_t)0;
#endif
}

cudaError_t nms_yxyx_per_class(
    const float* /*d_boxes*/,
    const float* /*d_scores*/,
    const int32_t* /*d_classes*/,
    int /*num*/,
    float /*iou_threshold*/,
    int* /*d_keep*/,
    int* kept_count,
    cudaStream_t /*stream*/) {
#if defined(USE_CUDA)
    if (kept_count) *kept_count = 0;
    return cudaErrorNotSupported;
#else
    if (kept_count) *kept_count = 0;
    return (cudaError_t)0;
#endif
}

#endif // !VA_HAS_CUDA_KERNELS

} // namespace va::analyzer::cudaops

