#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include "core/logger.hpp"
#include "analyzer/logging_util.hpp"
#include "core/global_metrics.hpp"
#include "core/cuda_tls.hpp"
#include <opencv2/imgproc.hpp>
#include <opencv2/core.hpp>
#include <vector>
#include <array>
#include <cmath>
#if defined(VA_HAS_CUDA_KERNELS)
#include "analyzer/cuda/overlay_kernels.hpp"
#include "analyzer/cuda/overlay_nv12_kernels.hpp"
#endif
#ifdef USE_CUDA
#include <cuda_runtime.h>
#endif

namespace va::analyzer {

bool OverlayRendererCUDA::draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) {
#ifdef USE_CUDA
    va::core::ensure_cuda_ready();
#endif
    auto log_once = [&](const char* path, size_t boxes, bool kernels, int thick, float alpha, const core::Frame& f){
        if (!debug_printed_) {
            auto lvl = va::analyzer::logutil::log_level_for_tag("overlay.cuda");
            auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("overlay.cuda");
            VA_LOG_THROTTLED(lvl, "overlay.cuda", thr)
                << "[OverlayCUDA] path=" << path
                << " boxes=" << boxes
                << " kernels=" << std::boolalpha << kernels
                << " thickness=" << thick
                << " alpha=" << alpha
                << " nv12_pitch0=" << (f.has_device_surface? f.device.pitch0:0)
                << " nv12_pitch1=" << (f.has_device_surface? f.device.pitch1:0);
            debug_printed_ = true;
        }
    };
    // Prefer NV12 device overlay if available (no text)
    // 若为 NV12 设备帧但当前无检测框，仍打印一次路径信息便于确认链路
    if (in.has_device_surface && in.device.on_gpu && in.device.fmt == core::PixelFormat::NV12 && output.boxes.empty()) {
#ifdef VA_HAS_CUDA_KERNELS
        const bool has_kernels = true;
#else
        const bool has_kernels = false;
#endif
        log_once("nv12-no-boxes", 0, has_kernels, 2, 0.0f, in);
        // metrics: NV12 passthrough hit
        va::core::GlobalMetrics::overlay_nv12_passthrough.fetch_add(1, std::memory_order_relaxed);
        if (in.zc) { in.zc->overlay_nv12_passthrough++; }
        // Pass-through NV12 device frame when no boxes; keep zero-copy path alive
        out = in;
        return true;
    }

    if (in.has_device_surface && in.device.on_gpu && in.device.fmt == core::PixelFormat::NV12 && !output.boxes.empty()) {
        out = in; // keep device surface and metadata
        const int w = in.device.width;
        const int h = in.device.height;
#if defined(VA_HAS_CUDA_KERNELS)
        // Kernel path (when CUDA kernels are built)
        {
            const int N = static_cast<int>(output.boxes.size());
            float* d_boxes = nullptr; int* d_cls = nullptr;
            if (cudaMalloc(&d_boxes, N * 4 * sizeof(float)) != cudaSuccess) {
                // fall through
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
                bool copied = (cudaMemcpy(d_boxes, h_boxes.data(), N*4*sizeof(float), cudaMemcpyHostToDevice) == cudaSuccess);
                if (copied) {
                    if (cudaMalloc(&d_cls, N * sizeof(int)) == cudaSuccess) {
                        if (cudaMemcpy(d_cls, h_cls.data(), N*sizeof(int), cudaMemcpyHostToDevice) != cudaSuccess) {
                            cudaFree(d_cls); d_cls = nullptr;
                        }
                    }
                    int thick = 2; float alpha = 0.0f;
                    if (const char* t = std::getenv("VA_OVERLAY_THICKNESS")) { try { thick = std::stoi(t); } catch (...) {} }
                    if (const char* a = std::getenv("VA_OVERLAY_ALPHA")) { try { alpha = std::stof(a); } catch (...) {} }
                    if (alpha > 0.0f) {
                        (void)va::analyzer::cudaops_nv12::fill_rects_nv12_inplace(
                            static_cast<uint8_t*>(in.device.data0), in.device.pitch0,
                            static_cast<uint8_t*>(in.device.data1), in.device.pitch1,
                            w, h, d_boxes, d_cls, N, alpha);
                    }
                    if (va::analyzer::cudaops_nv12::draw_rects_nv12_inplace(
                            static_cast<uint8_t*>(in.device.data0), in.device.pitch0,
                            static_cast<uint8_t*>(in.device.data1), in.device.pitch1,
                            w, h, d_boxes, d_cls, N, thick) == 0) {
                        log_once("nv12-kernel", output.boxes.size(), true, thick, alpha, in);
                        // metrics: NV12 kernel draw hit
                        va::core::GlobalMetrics::overlay_nv12_kernel_hits.fetch_add(1, std::memory_order_relaxed);
                        if (in.zc) { in.zc->overlay_nv12_kernel_hits++; }
                        if (d_cls) cudaFree(d_cls);
                        cudaFree(d_boxes);
                        return true; // in-place device overlay; no host copies
                    }
                }
                log_once("nv12-kernel-fallback", output.boxes.size(), true, 2, 0.0f, in);
                if (d_cls) cudaFree(d_cls);
                cudaFree(d_boxes);
            }
        }
#else
#ifdef USE_CUDA
        // Runtime-only path (no kernels): draw colored borders by memsets/memcpys
        {
            int thick = 2;
            if (const char* t = std::getenv("VA_OVERLAY_THICKNESS")) { try { thick = std::stoi(t); } catch (...) {} }
            const size_t yPitch = static_cast<size_t>(in.device.pitch0);
            const size_t uvPitch = static_cast<size_t>(in.device.pitch1);
            uint8_t* yBase = static_cast<uint8_t*>(in.device.data0);
            uint8_t* uvBase = static_cast<uint8_t*>(in.device.data1);
            bool ok_any = false;
            auto srgb_to_lin = [](float c){ return c <= 0.04045f ? c/12.92f : std::pow((c+0.055f)/1.055f, 2.4); };
            auto rgb_to_yuv709_limited = [&](unsigned char R8,unsigned char G8,unsigned char B8,
                                             unsigned char& Yc,unsigned char& Uc,unsigned char& Vc){
                float R = (float)srgb_to_lin(R8/255.0f);
                float G = (float)srgb_to_lin(G8/255.0f);
                float B = (float)srgb_to_lin(B8/255.0f);
                float Yf = 0.2126f*R + 0.7152f*G + 0.0722f*B;
                float Cb = (B - Yf) / 1.8556f;
                float Cr = (R - Yf) / 1.5748f;
                int yv = (int)std::round(16.0 + 219.0 * Yf);
                int uv = (int)std::round(128.0 + 224.0 * Cb);
                int vv = (int)std::round(128.0 + 224.0 * Cr);
                if (yv<16) yv=16; if (yv>235) yv=235; if (uv<16) uv=16; if (uv>240) uv=240; if (vv<16) vv=16; if (vv>240) vv=240;
                Yc=(unsigned char)yv; Uc=(unsigned char)uv; Vc=(unsigned char)vv;
            };
            auto color_for_class_bgr = [](int cls){
                static const unsigned char pal[20][3] = {
                    {255, 56, 56}, {255,157,151}, {255,112, 31}, {255,178, 29}, {207,210, 49},
                    { 72,249, 10}, {146,204, 23}, { 61,219,134}, { 26,147, 52}, {  0,212,187},
                    { 44,153,168}, {  0,194,255}, { 52, 69,147}, {100,115,255}, {  0, 24,236},
                    {132, 56,255}, { 82,  0,133}, {203, 56,255}, {255,149,200}, {255, 55,199}
                };
                int i = cls % 20; if (i<0) i+=20; return std::array<unsigned char,3>{pal[i][2], pal[i][1], pal[i][0]}; /* return R,G,B */
            };
            for (const auto& b : output.boxes) {
                int x1 = std::max(0, (int)std::round(b.x1));
                int y1 = std::max(0, (int)std::round(b.y1));
                int x2 = std::min(w-1, (int)std::round(b.x2));
                int y2 = std::min(h-1, (int)std::round(b.y2));
                if (x2 <= x1 || y2 <= y1) continue;
                int tb = std::max(1, thick);
                // Compute target YUV from class color
                auto rgb = color_for_class_bgr(b.cls); unsigned char Yc=235, Uc=128, Vc=128; rgb_to_yuv709_limited(rgb[0], rgb[1], rgb[2], Yc, Uc, Vc);
                // top/bottom bars on Y
                size_t rowBytes = (size_t)(x2 - x1 + 1);
                cudaError_t e1 = cudaMemset2D(yBase + y1 * yPitch + x1, yPitch, Yc, rowBytes, std::min(tb, y2 - y1 + 1));
                cudaError_t e2 = cudaMemset2D(yBase + std::max(y2 - tb + 1, y1) * yPitch + x1, yPitch, Yc, rowBytes, std::min(tb, y2 - y1 + 1));
                // left/right bars on Y
                size_t colBytes = (size_t)tb; // tb columns width
                cudaError_t e3 = cudaMemset2D(yBase + y1 * yPitch + x1, yPitch, Yc, colBytes, (size_t)(y2 - y1 + 1));
                cudaError_t e4 = cudaMemset2D(yBase + y1 * yPitch + std::max(x2 - tb + 1, x1), yPitch, Yc, colBytes, (size_t)(y2 - y1 + 1));
                // UV plane borders (colored)
                int uv_x1 = x1/2, uv_x2 = x2/2, uv_y1 = y1/2, uv_y2 = y2/2;
                size_t uvRowBytes = (size_t)((uv_x2 - uv_x1 + 1) * 2);
                const int ct = std::max(1, tb/2);
                // Build a UV row pattern [U,V] repeated across width
                std::vector<uint8_t> uvRow(uvRowBytes);
                for (size_t k=0;k<uvRowBytes;k+=2){ uvRow[k]=Uc; uvRow[k+1]=Vc; }
                // top rows
                cudaError_t e5 = cudaMemcpy2D(uvBase + uv_y1 * uvPitch + uv_x1*2, uvPitch, uvRow.data(), uvRowBytes, uvRowBytes, ct, cudaMemcpyHostToDevice);
                // bottom rows
                cudaError_t e6 = cudaMemcpy2D(uvBase + std::max(uv_y2 - ct + 1, uv_y1) * uvPitch + uv_x1*2, uvPitch, uvRow.data(), uvRowBytes, uvRowBytes, ct, cudaMemcpyHostToDevice);
                // left/right columns: copy a ct*2 stripe for each row
                size_t uvColBytes = (size_t)ct * 2;
                std::vector<uint8_t> uvCol(uvColBytes);
                for (size_t k=0;k<uvColBytes;k+=2){ uvCol[k]=Uc; uvCol[k+1]=Vc; }
                cudaError_t e7 = cudaSuccess, e8 = cudaSuccess;
                for (int uyy = uv_y1; uyy <= uv_y2; ++uyy) {
                    // left column
                    cudaError_t t1 = cudaMemcpy(uvBase + uyy * uvPitch + uv_x1*2, uvCol.data(), uvColBytes, cudaMemcpyHostToDevice);
                    // right column
                    int rx = std::max(uv_x2 - ct + 1, uv_x1);
                    cudaError_t t2 = cudaMemcpy(uvBase + uyy * uvPitch + rx*2, uvCol.data(), uvColBytes, cudaMemcpyHostToDevice);
                    if (e7==cudaSuccess && t1!=cudaSuccess) e7 = t1; if (e8==cudaSuccess && t2!=cudaSuccess) e8 = t2;
                }
                ok_any = ok_any || (e1==cudaSuccess && e2==cudaSuccess && e3==cudaSuccess && e4==cudaSuccess && e5==cudaSuccess && e6==cudaSuccess && e7==cudaSuccess && e8==cudaSuccess);
            }
            log_once("nv12-memset", output.boxes.size(), false, thick, 0.0f, in);
            if (ok_any) return true;
        }
#endif
#endif
        // If any error, fall through to CPU overlay
    }

    // Fallback GPU path: copy BGR to device, draw, copy back
#if defined(VA_HAS_CUDA_KERNELS)
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
#endif // VA_HAS_CUDA_KERNELS
    // Final fallback: CPU overlay
    OverlayRendererCPU cpu;
    bool ok = cpu.draw(in, output, out);
    log_once("cpu", output.boxes.size(), false, 2, 0.0f, in);
    return ok;
}

} 
