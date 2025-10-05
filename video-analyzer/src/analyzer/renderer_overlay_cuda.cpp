#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>
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
    if (cudaMalloc(&d_img, bytes) != cudaSuccess) { /* fallback below */ }
    else if (cudaMemcpy(d_img, in.bgr.data(), bytes, cudaMemcpyHostToDevice) != cudaSuccess) { cudaFree(d_img); d_img=nullptr; }
    const int N = static_cast<int>(output.boxes.size());
    if (d_img && N > 0) {
        if (cudaMalloc(&d_boxes, N*4*sizeof(float)) != cudaSuccess) goto CLEAN_IMG;
        if (cudaMalloc(&d_cls, N*sizeof(int32_t)) != cudaSuccess) goto CLEAN_BOXES;
        std::vector<float> h_boxes(N*4); std::vector<int32_t> h_cls(N);
        for (int i=0;i<N;++i){ h_boxes[i*4+0]=output.boxes[i].x1; h_boxes[i*4+1]=output.boxes[i].y1; h_boxes[i*4+2]=output.boxes[i].x2; h_boxes[i*4+3]=output.boxes[i].y2; h_cls[i]=output.boxes[i].cls; }
        if (cudaMemcpy(d_boxes, h_boxes.data(), N*4*sizeof(float), cudaMemcpyHostToDevice) != cudaSuccess) goto CLEAN_CLS;
        if (cudaMemcpy(d_cls, h_cls.data(), N*sizeof(int32_t), cudaMemcpyHostToDevice) != cudaSuccess) goto CLEAN_CLS;
        // optional filled mask first (alpha from env, default 0.3)
        float alpha = 0.3f; int thick = 2;
        if (const char* a = std::getenv("VA_OVERLAY_ALPHA")) { try { alpha = std::stof(a); } catch (...) {} }
        if (const char* t = std::getenv("VA_OVERLAY_THICKNESS")) { try { thick = std::stoi(t); } catch (...) {} }
        if (alpha > 0.0f) {
            (void)va::analyzer::cudaops::fill_rects_bgr_inplace(d_img, w, h, d_boxes, d_cls, N, alpha, nullptr);
        }
        if (va::analyzer::cudaops::draw_rects_bgr_inplace(d_img, w, h, d_boxes, d_cls, N, thick, nullptr) != cudaSuccess) goto CLEAN_CLS;
    }
    if (d_img && cudaMemcpy(out.bgr.data(), d_img, bytes, cudaMemcpyDeviceToHost) == cudaSuccess) {
        if (d_cls) cudaFree(d_cls);
        if (d_boxes) cudaFree(d_boxes);
        cudaFree(d_img);
        // Draw labels on CPU for clarity (class id and score)
        cv::Mat img(h, w, CV_8UC3, out.bgr.data());
        for (const auto& b : output.boxes) {
            char label[64];
            std::snprintf(label, sizeof(label), "id:%d %.0f%%", b.cls, b.score*100.0f);
            // color formula consistent with CUDA path
            cv::Scalar color(((233*b.cls + 53)%255), ((17*b.cls + 199)%255), ((37*b.cls + 97)%255)); // BGR
            int baseline=0; auto sz = cv::getTextSize(label, cv::FONT_HERSHEY_SIMPLEX, 0.5, 1, &baseline);
            int x = std::max(0, (int)std::round(b.x1));
            int y = std::max(0, (int)std::round(b.y1) - 4);
            cv::rectangle(img, cv::Rect(x, std::max(0,y - sz.height - 4), sz.width + 6, sz.height + 6), color, cv::FILLED);
            cv::putText(img, label, cv::Point(x+3, std::max(0,y - 3)), cv::FONT_HERSHEY_SIMPLEX, 0.5, cv::Scalar(255,255,255), 1, cv::LINE_AA);
        }
        return true;
    }
CLEAN_CLS:
    if (d_cls) cudaFree(d_cls);
CLEAN_BOXES:
    if (d_boxes) cudaFree(d_boxes);
CLEAN_IMG:
    if (d_img) cudaFree(d_img);
#endif
    {
        OverlayRendererCPU cpu;
        return cpu.draw(in, output, out);
    }
}

} 
