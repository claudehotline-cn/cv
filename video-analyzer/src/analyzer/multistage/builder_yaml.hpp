#pragma once

#include "analyzer/multistage/graph.hpp"
#include "analyzer/multistage/registry.hpp"

namespace va { namespace analyzer { namespace multistage {

// Build a graph from YAML file; returns true on success
bool build_graph_from_yaml(const std::string& file, Graph& g);

// Build with overrides: allows overriding node params by keys like
//  - node.<name>.<param>=value (applies to node by name)
//  - type:<type>.<param>=value (applies to all nodes of type)
// Engine-related overrides are ignored here and should be processed by the caller.
bool build_graph_from_yaml_with_overrides(
    const std::string& file,
    const std::unordered_map<std::string, std::string>& overrides,
    Graph& g);

} } } // namespace
