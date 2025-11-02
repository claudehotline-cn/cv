#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include <unordered_map>
#include <vector>

namespace va { namespace analyzer { namespace multistage {

// Draw keypoints and optional skeleton on CPU BGR frame.
// Input tensor: [N,K,3] (x,y,score) under key `in` (default: tensor:kpt)
// Params:
//  - in: tensor key (default tensor:kpt)
//  - radius: int (default 3)
//  - thickness: int (default 2)
//  - min_score: float (default 0.0)
//  - draw_skeleton: int/bool (default 0)
//  - skeleton: CSV pairs like "0-1,1-2,2-3" (optional)
class NodeOverlayKpt : public INode {
public:
    explicit NodeOverlayKpt(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> inputs() const override { return {in_key_}; }
private:
    std::string in_key_ {"tensor:kpt"};
    int radius_ {3};
    int thickness_ {2};
    float min_score_ {0.0f};
    bool draw_skeleton_ {false};
    std::vector<std::pair<int,int>> edges_;
};

} } } // namespace

