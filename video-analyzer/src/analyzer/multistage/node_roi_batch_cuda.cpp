#include "analyzer/multistage/node_roi_batch_cuda.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "analyzer/multistage/node_roi_batch.hpp"
#include "analyzer/cuda/preproc_letterbox_kernels.hpp"
#include "core/logger.hpp"
#include <cmath>

using va::analyzer::multistage::util::get_or_int;

#ifdef USE_CUDA
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_RBC_HAS_CUDA 1
#    else
#      define VA_MS_RBC_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_RBC_HAS_CUDA 1
#  endif
#else
#  define VA_MS_RBC_HAS_CUDA 0
#endif

namespace va { namespace analyzer { namespace multistage {

NodeRoiBatchCuda::NodeRoiBatchCuda(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in_rois"); it != cfg.end()) in_rois_key_ = it->second;
    if (auto it = cfg.find("out"); it != cfg.end()) out_key_ = it->second;
    out_w_ = get_or_int(cfg, "out_w", 128);
    out_h_ = get_or_int(cfg, "out_h", 128);
    max_rois_ = get_or_int(cfg, "max_rois", 0);
}

bool NodeRoiBatchCuda::process(Packet& p, NodeContext& ctx) {
    auto it = p.rois.find(in_rois_key_);
    if (it == p.rois.end()) { p.tensors.erase(out_key_); return true; }
    const auto& rois = it->second;
    last_total_rois_ = static_cast<int>(rois.size());
    staged_.clear();

#if VA_MS_RBC_HAS_CUDA && defined(VA_HAS_CUDA_KERNELS)
    if (p.frame.has_device_surface && p.frame.device.on_gpu && p.frame.device.fmt == va::core::PixelFormat::NV12) {
        const int src_w = p.frame.device.width;
        const int src_h = p.frame.device.height;
        const uint8_t* d_y  = static_cast<const uint8_t*>(p.frame.device.data0);
        const uint8_t* d_uv = static_cast<const uint8_t*>(p.frame.device.data1);
        const int pitch_y  = p.frame.device.pitch0;
        const int pitch_uv = p.frame.device.pitch1;
        int use_n = static_cast<int>(rois.size());
        if (max_rois_ > 0) use_n = std::min(use_n, max_rois_);
        last_used_rois_ = use_n;
        if (use_n <= 0) { p.tensors.erase(out_key_); return true; }

        // Allocate one contiguous device buffer: N*3*H*W floats
        const size_t plane = static_cast<size_t>(out_w_) * static_cast<size_t>(out_h_);
        const size_t out_bytes = static_cast<size_t>(use_n) * 3ull * plane * sizeof(float);
        va::core::GpuBufferPool* pool = ctx.gpu_pool;
        if (!pool) {
            if (!local_pool_) local_pool_ = std::make_unique<va::core::GpuBufferPool>(out_bytes, 2);
            pool = local_pool_.get();
        }
        auto mem = pool->acquire(out_bytes);
        if (!mem.ptr) { VA_LOG_C(::va::core::LogLevel::Warn, "ms.roi_batch.cuda") << "gpu_pool acquire failed"; return false; }
        staged_.push_back(std::move(mem));
        float* d_base = static_cast<float*>(staged_.back().ptr);

        for (int i = 0; i < use_n; ++i) {
            auto b = rois[i];
            int x1 = std::max(0, (int)std::floor(b.x1));
            int y1 = std::max(0, (int)std::floor(b.y1));
            int x2 = std::min(src_w - 1, (int)std::ceil(b.x2));
            int y2 = std::min(src_h - 1, (int)std::ceil(b.y2));
            if (x2 <= x1 || y2 <= y1) continue;
            const int rw = x2 - x1 + 1;
            const int rh = y2 - y1 + 1;
            // Compute letterbox params for ROI -> out_w_/out_h_
            float scale = std::min((float)out_w_ / rw, (float)out_h_ / rh);
            int dst_w = std::max(1, (int)std::round(rw * scale));
            int dst_h = std::max(1, (int)std::round(rh * scale));
            int pad_x = (out_w_ - dst_w) / 2;
            int pad_y = (out_h_ - dst_h) / 2;
            const uint8_t* roi_y  = d_y  + y1 * pitch_y  + x1;
            const uint8_t* roi_uv = d_uv + (y1/2) * pitch_uv + (x1/2)*2;
            float* d_out = d_base + static_cast<size_t>(i) * 3ull * plane;
            auto err = va::analyzer::cudaops::letterbox_nv12_to_nchw_fp32(
                roi_y, pitch_y, roi_uv, pitch_uv,
                rw, rh, out_w_, out_h_, d_out,
                scale, pad_x, pad_y, true,
                reinterpret_cast<cudaStream_t>(ctx.stream));
            if (err != cudaSuccess) {
                VA_LOG_C(::va::core::LogLevel::Warn, "ms.roi_batch.cuda") << "letterbox_nv12_to_nchw_fp32 error: " << (int)err;
                // continue to next ROI; output region remains zero
            }
        }
        va::core::TensorView tv;
        tv.data = d_base;
        tv.shape = { use_n, 3, out_h_, out_w_ };
        tv.dtype = va::core::DType::F32;
        tv.on_gpu = true;
        p.tensors[out_key_] = tv;
        return true;
    }
#endif
    // Fallback: CPU roi.batch
    {
        static thread_local std::unique_ptr<NodeRoiBatch> cpu;
        if (!cpu) cpu = std::make_unique<NodeRoiBatch>(std::unordered_map<std::string,std::string>{{"in_rois",in_rois_key_},{"out",out_key_},{"out_w",std::to_string(out_w_)},{"out_h",std::to_string(out_h_)},{"max_rois",std::to_string(max_rois_)}});
        bool ok = cpu->process(p, ctx);
        last_used_rois_ = std::min(last_total_rois_, max_rois_>0? max_rois_: last_total_rois_);
        return ok;
    }
}

} } } // namespace
