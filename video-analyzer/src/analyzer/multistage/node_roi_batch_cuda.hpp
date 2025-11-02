#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include "core/gpu_buffer_pool.hpp"
#include <unordered_map>
#include <vector>

namespace va { namespace analyzer { namespace multistage {

// GPU ROI batch letterbox: NV12 device surface -> NCHW/F32 on device
// Params:
//  - in_rois: string (default "det")
//  - out: string tensor key (default "tensor:roi_batch")
//  - out_w/out_h: int (default 128/128)
//  - max_rois: int (default 0 = all)
class NodeRoiBatchCuda : public INode {
public:
    explicit NodeRoiBatchCuda(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_rois_key_}; }
    std::vector<std::string> outputs() const override { return {out_key_}; }
    // Introspection (best-effort): last total/used ROIs
    int last_total_rois() const { return last_total_rois_; }
    int last_used_rois() const { return last_used_rois_; }
private:
    std::string in_rois_key_ {"det"};
    std::string out_key_ {"tensor:roi_batch"};
    int out_w_ {128};
    int out_h_ {128};
    int max_rois_ {0};
    std::unique_ptr<va::core::GpuBufferPool> local_pool_;
    std::vector<va::core::GpuBufferPool::Memory> staged_;
    int last_total_rois_ {0};
    int last_used_rois_ {0};
};

} } } // namespace
