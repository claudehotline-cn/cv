#pragma once

#include "control_plane_embedded/interfaces.hpp"
#include "analyzer/multistage/graph.hpp"

namespace va { namespace core { class EngineManager; } }

namespace va { namespace control {

class GraphAdapterYaml : public IGraphAdapter {
public:
    GraphAdapterYaml() = default;
    explicit GraphAdapterYaml(va::core::EngineManager* em) : engine_manager_(em) {}
    OpaquePtr BuildGraph(const PlainPipelineSpec& spec, std::string* err) override;
    std::unique_ptr<IExecutor> CreateExecutor(void* graph, std::string* err) override;
private:
    va::core::EngineManager* engine_manager_ {nullptr};
    // Cache last overrides for executor startup (engine.options.*)
    std::unordered_map<std::string,std::string> overrides_cache_;
};

} } // namespace
