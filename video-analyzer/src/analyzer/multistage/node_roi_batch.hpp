#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include <unordered_map>
#include <vector>

namespace va { namespace analyzer { namespace multistage {

// Batches ROI crops from Packet.frame into an NCHW/F32 tensor on host.
// Params:
//  - in_rois: string (default "det")
//  - out: string tensor key (default "tensor:roi_batch")
//  - out_w/out_h: int (default 128/128)
//  - normalize: int/bool (default 1) scale to [0,1]
//  - max_rois: int (optional, 0 means all)
class NodeRoiBatch : public INode {
public:
    explicit NodeRoiBatch(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_rois_key_}; }
    std::vector<std::string> outputs() const override { return {out_key_}; }
    int last_total_rois() const { return last_total_rois_; }
    int last_used_rois() const { return last_used_rois_; }
private:
    std::string in_rois_key_ {"det"};
    std::string out_key_ {"tensor:roi_batch"};
    int out_w_ {128};
    int out_h_ {128};
    bool normalize_ {true};
    int max_rois_ {0};
    std::vector<float> buffer_;
    int last_total_rois_ {0};
    int last_used_rois_ {0};
};

} } } // namespace
