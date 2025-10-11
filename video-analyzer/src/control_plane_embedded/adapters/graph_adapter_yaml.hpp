#pragma once

#include "control_plane_embedded/interfaces.hpp"
#include "analyzer/multistage/graph.hpp"

namespace va { namespace control {

class GraphAdapterYaml : public IGraphAdapter {
public:
    OpaquePtr BuildGraph(const PlainPipelineSpec& spec, std::string* err) override;
    std::unique_ptr<IExecutor> CreateExecutor(void* graph, std::string* err) override;
};

} } // namespace
