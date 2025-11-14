#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "analyzer/postproc_yolo_det.hpp"
#include "core/logger.hpp"
#include "core/engine_manager.hpp"
#include "analyzer/logging_util.hpp"
#include <algorithm>

using va::analyzer::multistage::util::get_or_float;

namespace va { namespace analyzer { namespace multistage {

NodeNmsYolo::NodeNmsYolo(const std::unordered_map<std::string,std::string>& cfg) {
    conf_ = get_or_float(cfg, "conf", 0.25f);
    iou_  = get_or_float(cfg, "iou", 0.45f);
    // Optional toggle to prefer CUDA NMS in this node
    prefer_cuda_ = (get_or_float(cfg, "use_cuda", 0.0f) != 0.0f);
}

bool NodeNmsYolo::process(Packet& p, NodeContext& ctx) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
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
    // Export as rois
    p.rois["det"] = mo.boxes;
    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms");
    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms");
    VA_LOG_THROTTLED(lvl, "ms.nms", thr) << "boxes=" << mo.boxes.size();
    return true;
}

} } } // namespace
