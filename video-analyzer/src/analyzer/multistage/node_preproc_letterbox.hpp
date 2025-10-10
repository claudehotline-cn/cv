#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include <unordered_map>

namespace va { namespace analyzer { namespace multistage {

class NodePreprocLetterbox : public INode {
public:
    explicit NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg);
    bool process(Packet& p, NodeContext& ctx) override;
    std::vector<std::string> outputs() const override { return {"tensor:det_input"}; }
private:
    int out_h_ {640}, out_w_ {640}, out_c_ {3};
    bool prefer_cuda_ {true};
};

} } } // namespace

