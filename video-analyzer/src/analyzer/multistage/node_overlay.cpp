#include "analyzer/multistage/node_overlay.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include "analyzer/renderer_overlay_cuda.hpp"
#include "core/logger.hpp"

namespace va { namespace analyzer { namespace multistage {

NodeOverlay::NodeOverlay(const std::unordered_map<std::string,std::string>& cfg) {
    auto it = cfg.find("rois"); if (it != cfg.end()) rois_key_ = it->second;
}

bool NodeOverlay::open(NodeContext& /*ctx*/) {
#ifdef USE_CUDA
    if (prefer_cuda_) renderer_ = std::make_shared<va::analyzer::OverlayRendererCUDA>();
#endif
    if (!renderer_) renderer_ = std::make_shared<va::analyzer::OverlayRendererCPU>();
    return true;
}

bool NodeOverlay::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.rois.find(rois_key_);
    va::core::ModelOutput mo;
    if (it != p.rois.end()) mo.boxes = it->second;
    va::core::Frame out;
    const size_t n = mo.boxes.size();
    if (!renderer_->draw(p.frame, mo, out)) return false;
    VA_LOG_C(::va::core::LogLevel::Info, "ms.overlay") << "drawn boxes=" << n;
    p.frame = out;
    return true;
}

} } } // namespace
