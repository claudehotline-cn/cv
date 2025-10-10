#pragma once

#include "analyzer/multistage/graph.hpp"
#include "analyzer/multistage/registry.hpp"

namespace va { namespace analyzer { namespace multistage {

// Build a graph from YAML file; returns true on success
bool build_graph_from_yaml(const std::string& file, Graph& g);

} } } // namespace

