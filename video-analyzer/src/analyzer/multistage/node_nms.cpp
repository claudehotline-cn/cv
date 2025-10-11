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
    std::vector<va::core::TensorView> raw{it->second};
    va::core::ModelOutput mo;
    bool use_cuda_nms = prefer_cuda_;
    if (ctx.engine_registry) {
        try {
            auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
            auto desc = em->currentEngine();
            auto itopt = desc.options.find("use_cuda_nms");
            if (itopt != desc.options.end()) {
                std::string v = itopt->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                use_cuda_nms = use_cuda_nms || (v=="1"||v=="true"||v=="yes"||v=="on");
            }
        } catch (...) {}
    }
    if (use_cuda_nms) {
#ifdef USE_CUDA
        va::analyzer::YoloDetectionPostprocessorCUDA gpu_pp;
        if (!gpu_pp.run(raw, p.letterbox, mo)) return false;
#else
        va::analyzer::YoloDetectionPostprocessor cpu_pp;
        if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
#endif
    } else {
        va::analyzer::YoloDetectionPostprocessor cpu_pp;
        if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
    }
    // Export as rois
    p.rois["det"] = mo.boxes;
    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.nms");
    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.nms");
    VA_LOG_THROTTLED(lvl, "ms.nms", thr) << "boxes=" << mo.boxes.size();
    return true;
}

} } } // namespace
