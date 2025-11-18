#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "analyzer/postproc_yolo_det.hpp"
#include "core/logger.hpp"
#include "core/engine_manager.hpp"
#include "analyzer/logging_util.hpp"
#include <algorithm>

// 本节点内部按需使用 CUDA 运行时（仅在 USE_CUDA 且存在 cuda_runtime.h 时启用）
#ifdef USE_CUDA
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_NMS_HAS_CUDA 1
#    else
#      define VA_MS_NMS_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_NMS_HAS_CUDA 1
#  endif
#else
#  define VA_MS_NMS_HAS_CUDA 0
#endif

using va::analyzer::multistage::util::get_or_float;

namespace va { namespace analyzer { namespace multistage {

NodeNmsYolo::NodeNmsYolo(const std::unordered_map<std::string,std::string>& cfg) {
    conf_ = get_or_float(cfg, "conf", 0.25f);
    iou_  = get_or_float(cfg, "iou", 0.45f);
    // Optional toggle to prefer CUDA NMS in this node
    prefer_cuda_ = (get_or_float(cfg, "use_cuda", 0.0f) != 0.0f);
    // Optional: emit GPU ROI view for zero-copy pipelines
    float emit_gpu = get_or_float(cfg, "emit_gpu_rois", 0.0f);
    emit_gpu_rois_ = (emit_gpu != 0.0f);
}

bool NodeNmsYolo::process(Packet& p, NodeContext& ctx) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    // 释放上一帧为 GPU ROI 分配的缓冲，避免长时间运行时显存不断增长
    if (gpu_boxes_mem_.ptr && gpu_pool_) {
        gpu_pool_->release(std::move(gpu_boxes_mem_));
        gpu_boxes_mem_ = {};
    }
    {
        // 输入形状与cuda偏好日志
        std::string shp; for (size_t i=0;i<it->second.shape.size();++i){ shp += (i?"x":""); shp += std::to_string(it->second.shape[i]); }
        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms");
        VA_LOG_THROTTLED(lvl, "ms.nms", thr) << "in_key='" << in_key_ << "' shape=" << shp << " on_gpu=" << std::boolalpha << it->second.on_gpu << " prefer_cuda=" << prefer_cuda_;
    }
    std::vector<va::core::TensorView> raw{it->second};
    va::core::ModelOutput mo;
    // Bridge graph-level thresholds到后处理（通过环境变量，避免大范围改动接口）
// thresholds injected via setThresholds(conf_, iou_)
    bool use_cuda_nms = prefer_cuda_;
    bool prefer_fp16  = false;
    if (ctx.engine_registry) {
        try {
            auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
            auto desc = em->currentEngine();
            auto itopt = desc.options.find("use_cuda_nms");
            if (itopt != desc.options.end()) {
                std::string v = itopt->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                use_cuda_nms = use_cuda_nms || (v=="1"||v=="true"||v=="yes"||v=="on");
            }
            // GPU 精度配置：通过 engine.options 中的 yolo_decode_fp16 控制是否优先使用 FP16 decode
            auto itprec = desc.options.find("yolo_decode_fp16");
            if (itprec != desc.options.end()) {
                std::string v = itprec->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                prefer_fp16 = (v=="1"||v=="true"||v=="yes"||v=="on");
            }
        } catch (...) {}
    }
    // Decide code path. Prefer CUDA when requested; fallback to CPU on failure
    if (use_cuda_nms) {
#ifdef USE_CUDA
        va::analyzer::YoloDetectionPostprocessorCUDA gpu_pp;
        gpu_pp.setStream(ctx.stream);
        gpu_pp.setPreferFp16(prefer_fp16);
        gpu_pp.setThresholds(conf_, iou_);
        if (!gpu_pp.run(raw, p.letterbox, mo)) {
            auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms"); auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms");
            VA_LOG_THROTTLED(lvl, "ms.nms", thr) << "gpu_nms_run=false -> fallback cpu";
            // Fallback to CPU postproc if CUDA path fails (keep pipeline alive)
            va::analyzer::YoloDetectionPostprocessor cpu_pp; cpu_pp.setThresholds(conf_, iou_); if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
        }
#else
        va::analyzer::YoloDetectionPostprocessor cpu_pp; cpu_pp.setThresholds(conf_, iou_); if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
#endif
    } else {
        va::analyzer::YoloDetectionPostprocessor cpu_pp; cpu_pp.setThresholds(conf_, iou_); if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
    }
    // Export as CPU rois
    p.rois["det"] = mo.boxes;

    // Optional: also emit GPU ROI buffer for downstream GPU-only nodes.
    if (emit_gpu_rois_ && ctx.gpu_pool) {
#if VA_MS_NMS_HAS_CUDA
        const std::size_t n = mo.boxes.size();
        if (n > 0) {
            // Allocate a GPU buffer for [N,4] boxes (x1,y1,x2,y2)
            const std::size_t elems = n * 4;
            gpu_pool_ = ctx.gpu_pool;
            if (gpu_boxes_mem_.ptr && gpu_boxes_mem_.bytes < elems * sizeof(float)) {
                // 当前缓存不足时先归还旧块，再申请更大的块
                gpu_pool_->release(std::move(gpu_boxes_mem_));
                gpu_boxes_mem_ = {};
            }
            if (!gpu_boxes_mem_.ptr) {
                gpu_boxes_mem_ = gpu_pool_->acquire(elems * sizeof(float));
            }
            if (gpu_boxes_mem_.ptr) {
                // Prepare a temporary host buffer and copy to device once.
                std::vector<float> host_boxes(elems);
                for (std::size_t i = 0; i < n; ++i) {
                    const auto& b = mo.boxes[i];
                    host_boxes[i * 4 + 0] = b.x1;
                    host_boxes[i * 4 + 1] = b.y1;
                    host_boxes[i * 4 + 2] = b.x2;
                    host_boxes[i * 4 + 3] = b.y2;
                }
                cudaMemcpyAsync(gpu_boxes_mem_.ptr, host_boxes.data(),
                                elems * sizeof(float),
                                cudaMemcpyHostToDevice,
                                static_cast<cudaStream_t>(ctx.stream));
                GpuRoiBuffer buf;
                buf.d_boxes = static_cast<float*>(gpu_boxes_mem_.ptr);
                buf.d_scores = nullptr; // 可按需扩展
                buf.d_cls = nullptr;    // 可按需扩展
                buf.count = static_cast<int32_t>(n);
                p.gpu_rois["det"] = buf;
            }
        }
#endif
    }
    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms");
    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms");
    VA_LOG_THROTTLED(lvl, "ms.nms", thr) << "boxes=" << mo.boxes.size();
    return true;
}

void NodeNmsYolo::close(NodeContext& ctx) {
    (void)ctx;
#if VA_MS_NMS_HAS_CUDA
    if (gpu_boxes_mem_.ptr) {
        if (gpu_pool_) {
            gpu_pool_->release(std::move(gpu_boxes_mem_));
        } else {
            // 理论上不会走到这里，作为兜底直接释放
            cudaFree(gpu_boxes_mem_.ptr);
        }
        gpu_boxes_mem_ = {};
    }
    gpu_pool_ = nullptr;
#endif
}

} } } // namespace
