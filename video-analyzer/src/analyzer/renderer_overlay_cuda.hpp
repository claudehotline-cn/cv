#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer { namespace multistage { struct GpuRoiBuffer; } }

namespace va::analyzer {

class OverlayRendererCUDA : public IRenderer {
public:
    void setStream(void* s) { stream_ = s; }
    bool draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) override;
    // 直接从 GPU ROI 视图绘制边框（避免 CPU rois 往返拷贝）
    bool draw_gpu_rois(const core::Frame& in,
                       const multistage::GpuRoiBuffer& rois,
                       core::Frame& out);
private:
    mutable bool debug_printed_{false};
    void* stream_ {nullptr};
};

}
