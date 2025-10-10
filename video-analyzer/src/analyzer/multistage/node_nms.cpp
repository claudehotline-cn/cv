#include "analyzer/multistage/node_nms.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "analyzer/postproc_yolo_det.hpp"

using va::analyzer::multistage::util::get_or_float;

namespace va { namespace analyzer { namespace multistage {

NodeNmsYolo::NodeNmsYolo(const std::unordered_map<std::string,std::string>& cfg) {
    conf_ = get_or_float(cfg, "conf", 0.25f);
    iou_  = get_or_float(cfg, "iou", 0.45f);
}

bool NodeNmsYolo::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    std::vector<va::core::TensorView> raw{it->second};
    va::core::ModelOutput mo;
    {
        va::analyzer::YoloDetectionPostprocessor cpu_pp;
        // Thresholds use existing implementation defaults / env (VA_CONF_THRESH)
        if (!cpu_pp.run(raw, p.letterbox, mo)) return false;
    }
    // Export as rois
    p.rois["det"] = mo.boxes;
    return true;
}

} } } // namespace
