#include "analyzer/multistage/node_overlay.hpp"
#include "analyzer/renderer_overlay_cpu.hpp"
#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/logging_util.hpp"
#include "core/logger.hpp"

namespace va { namespace analyzer { namespace multistage {

NodeOverlay::NodeOverlay(const std::unordered_map<std::string,std::string>& cfg) {
    auto it = cfg.find("rois"); if (it != cfg.end()) rois_key_ = it->second;
    auto it_gpu = cfg.find("use_gpu_rois");
    if (it_gpu != cfg.end()) {
        const std::string& v = it_gpu->second;
        if (v == "1" || v == "true" || v == "on" || v == "yes") {
            use_gpu_rois_ = true;
        }
    }
}

bool NodeOverlay::open(NodeContext& /*ctx*/) {
#ifdef USE_CUDA
    if (prefer_cuda_) renderer_ = std::make_shared<va::analyzer::OverlayRendererCUDA>();
#endif
    if (!renderer_) renderer_ = std::make_shared<va::analyzer::OverlayRendererCPU>();
    return true;
}

bool NodeOverlay::process(Packet& p, NodeContext& ctx) {
    auto it = p.rois.find(rois_key_);
    va::core::ModelOutput mo;
    if (it != p.rois.end()) mo.boxes = it->second;
    va::core::Frame out;
    const size_t n = mo.boxes.size();
    if (auto gpu = std::dynamic_pointer_cast<va::analyzer::OverlayRendererCUDA>(renderer_)) {
        // 将统一流传入 CUDA 渲染器
        gpu->setStream(ctx.stream);
        if (use_gpu_rois_) {
            auto git = p.gpu_rois.find(rois_key_);
            if (git != p.gpu_rois.end()) {
                if (gpu->draw_gpu_rois(p.frame, git->second, out)) {
                    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.overlay");
                    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.overlay");
                    VA_LOG_THROTTLED(lvl, "ms.overlay", thr) << "drawn boxes(gpu_rois)=" << git->second.count;
                    p.frame = out;
                    return true;
                }
            }
        }
    }
    if (!renderer_->draw(p.frame, mo, out)) return false;
    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.overlay");
    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.overlay");
    VA_LOG_THROTTLED(lvl, "ms.overlay", thr) << "drawn boxes=" << n;
    p.frame = out;
    return true;
}

} } } // namespace
