#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include "analyzer/interfaces.hpp" // IRenderer

namespace va { namespace analyzer { namespace multistage {

class NodeOverlay : public INode {
public:
    explicit NodeOverlay(const std::unordered_map<std::string,std::string>& cfg);
    bool open(NodeContext&) override;
    bool process(Packet& p, NodeContext& ctx) override;
private:
    std::string rois_key_ {"det"};
    // Renderer resolved in open() via context (or created lazily)
    std::shared_ptr<va::analyzer::IRenderer> renderer_;
    bool prefer_cuda_ {true};
};

} } } // namespace

