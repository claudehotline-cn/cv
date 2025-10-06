#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>
#if defined(VA_HAS_CUDA_KERNELS)
#include "analyzer/cuda/overlay_kernels.hpp"
#include "analyzer/cuda/overlay_nv12_kernels.hpp"
#endif

namespace va::analyzer {

bool OverlayRendererCUDA::draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) {
    // Prefer NV12 device overlay if available (no text)
#if defined(VA_HAS_CUDA_KERNELS)
    if (in.has_device_surface && in.device.on_gpu && in.device.fmt == core::PixelFormat::NV12 && !output.boxes.empty()) {
        out = in; // keep device surface and metadata
        const int w = in.device.width;
        const int h = in.device.height;
        // Prepare device buffers for boxes
        const int N = static_cast<int>(output.boxes.size());
        float* d_boxes = nullptr; int* d_cls = nullptr;
        if (cudaMalloc(&d_boxes, N * 4 * sizeof(float)) != cudaSuccess) {
            // fallback to CPU renderer below
        } else {
            std::vector<float> h_boxes(N*4);
            std::vector<int> h_cls(N, 0);
            for (int i=0;i<N;++i) {
                h_boxes[i*4+0] = output.boxes[i].x1;
                h_boxes[i*4+1] = output.boxes[i].y1;
                h_boxes[i*4+2] = output.boxes[i].x2;
                h_boxes[i*4+3] = output.boxes[i].y2;
                h_cls[i] = output.boxes[i].cls;
            }
            if (cudaMemcpy(d_boxes, h_boxes.data(), N*4*sizeof(float), cudaMemcpyHostToDevice) == cudaSuccess) {
                int thick = 2; float alpha = 0.0f;
                if (const char* t = std::getenv("VA_OVERLAY_THICKNESS")) { try { thick = std::stoi(t); } catch (...) {} }
                if (const char* a = std::getenv("VA_OVERLAY_ALPHA")) { try { alpha = std::stof(a); } catch (...) {} }
                if (alpha > 0.0f) {
                    (void)va::analyzer::cudaops_nv12::fill_rects_nv12_inplace(
                        static_cast<uint8_t*>(in.device.data0), in.device.pitch0,
                        static_cast<uint8_t*>(in.device.data1), in.device.pitch1,
                        w, h, d_boxes, nullptr, N, alpha);
                }
                if (va::analyzer::cudaops_nv12::draw_rects_nv12_inplace(
                        static_cast<uint8_t*>(in.device.data0), in.device.pitch0,
                        static_cast<uint8_t*>(in.device.data1), in.device.pitch1,
                        w, h, d_boxes, nullptr, N, thick) == 0) {
                    cudaFree(d_boxes);
                    return true; // in-place device overlay; no host copies
                }
            }
            cudaFree(d_boxes);
        }
        // If any error, fall through to CPU overlay
    }

    // Fallback GPU path: copy BGR to device, draw, copy back
    if (in.width > 0 && in.height > 0 && !in.bgr.empty()) {
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
            return true;
        }
CLEAN_CLS:
        if (d_cls) cudaFree(d_cls);
CLEAN_BOXES:
        if (d_boxes) cudaFree(d_boxes);
CLEAN_IMG:
        if (d_img) cudaFree(d_img);
    }
#endif
    // Final fallback: CPU overlay
    OverlayRendererCPU cpu;
    return cpu.draw(in, output, out);
}

} 
