#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#if defined(VA_HAS_CUDA_KERNELS)
#include "analyzer/cuda/overlay_kernels.hpp"
#endif

namespace va::analyzer {

bool OverlayRendererCUDA::draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) {
    // Try GPU overlay (copy-to-device and back); fallback to CPU on any error
#if defined(VA_HAS_CUDA_KERNELS)
    if (in.width <= 0 || in.height <= 0 || in.bgr.empty()) {
        return false;
    }
    out = in;
    const int w = in.width, h = in.height;
    const size_t bytes = static_cast<size_t>(w) * static_cast<size_t>(h) * 3ull;
    uint8_t* d_img = nullptr; float* d_boxes = nullptr; int32_t* d_cls = nullptr;
    if (cudaMalloc(&d_img, bytes) != cudaSuccess) goto CPU_FALLBACK;
    if (cudaMemcpy(d_img, in.bgr.data(), bytes, cudaMemcpyHostToDevice) != cudaSuccess) goto CLEAN_IMG;
    const int N = static_cast<int>(output.boxes.size());
    if (N > 0) {
        if (cudaMalloc(&d_boxes, N*4*sizeof(float)) != cudaSuccess) goto CLEAN_IMG;
        if (cudaMalloc(&d_cls, N*sizeof(int32_t)) != cudaSuccess) goto CLEAN_BOXES;
        std::vector<float> h_boxes(N*4); std::vector<int32_t> h_cls(N);
        for (int i=0;i<N;++i){ h_boxes[i*4+0]=output.boxes[i].x1; h_boxes[i*4+1]=output.boxes[i].y1; h_boxes[i*4+2]=output.boxes[i].x2; h_boxes[i*4+3]=output.boxes[i].y2; h_cls[i]=output.boxes[i].cls; }
        if (cudaMemcpy(d_boxes, h_boxes.data(), N*4*sizeof(float), cudaMemcpyHostToDevice) != cudaSuccess) goto CLEAN_CLS;
        if (cudaMemcpy(d_cls, h_cls.data(), N*sizeof(int32_t), cudaMemcpyHostToDevice) != cudaSuccess) goto CLEAN_CLS;
        if (va::analyzer::cudaops::draw_rects_bgr_inplace(d_img, w, h, d_boxes, d_cls, N, 2, nullptr) != cudaSuccess) goto CLEAN_CLS;
    }
    if (cudaMemcpy(out.bgr.data(), d_img, bytes, cudaMemcpyDeviceToHost) != cudaSuccess) goto CLEAN_CLS;
    if (d_cls) cudaFree(d_cls);
    if (d_boxes) cudaFree(d_boxes);
    if (d_img) cudaFree(d_img);
    return true;
CLEAN_CLS:
    if (d_cls) cudaFree(d_cls);
CLEAN_BOXES:
    if (d_boxes) cudaFree(d_boxes);
CLEAN_IMG:
    if (d_img) cudaFree(d_img);
#endif
CPU_FALLBACK:
    {
        OverlayRendererCPU cpu;
        return cpu.draw(in, output, out);
    }
}

} 
