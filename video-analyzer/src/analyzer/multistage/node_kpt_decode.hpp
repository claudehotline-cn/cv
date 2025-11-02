#pragma once

#include "analyzer/multistage/interfaces.hpp"

namespace va { namespace analyzer { namespace multistage {

// Decode YOLO-like keypoints from model raw tensor into [N,K,3] (x,y,score) in original image coords.
// Assumes input tensor shape is [1, C, N] or [1, N, C], where C = 4(box) + num_kpt*3 or exactly num_kpt*3.
// Params:
//  - in: input tensor key (default "tensor:det_raw")
//  - out: output tensor key (default "tensor:kpt")
//  - kpt_offset: int (default 5) start channel index for keypoints when boxes present
//  - min_score: float (default 0.0) score threshold for keypoints
class NodeKptDecode : public INode {
public:
    explicit NodeKptDecode(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_key_}; }
    std::vector<std::string> outputs() const override { return {out_key_}; }
private:
    std::string in_key_ {"tensor:det_raw"};
    std::string out_key_ {"tensor:kpt"};
    int kpt_offset_ {5};
    float min_score_ {0.0f};
    std::vector<float> buffer_;
};

} } } // namespace

