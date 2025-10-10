#include "analyzer/multistage/builder_yaml.hpp"
#include "analyzer/multistage/registry.hpp"
#include "core/logger.hpp"
#include <yaml-cpp/yaml.h>

namespace va { namespace analyzer { namespace multistage {

static std::unordered_map<std::string,std::string> to_map(const YAML::Node& n) {
    std::unordered_map<std::string,std::string> m;
    if (!n || !n.IsMap()) return m;
    for (auto it : n) {
        m[it.first.as<std::string>()] = it.second.as<std::string>();
    }
    return m;
}

bool build_graph_from_yaml(const std::string& file, Graph& g) {
    YAML::Node root = YAML::LoadFile(file);
    YAML::Node ms = root["analyzer"]["multistage"];
    if (!ms) ms = root["multistage"]; // allow top-level
    if (!ms) return false;
    std::unordered_map<std::string,int> name2id;
    // Nodes
    auto nodes = ms["nodes"];
    if (!nodes || !nodes.IsSequence()) return false;
    for (auto nd : nodes) {
        std::string name = nd["name"].as<std::string>();
        std::string type = nd["type"].as<std::string>();
        auto params = to_map(nd["params"]);
        auto node = NodeRegistry::instance().create(type, params);
        int id = g.add_node(name, node, type, params);
        name2id[name] = id;
    }
    // Edges
    auto edges = ms["edges"];
    if (edges && edges.IsSequence()) {
        for (auto e : edges) {
            if (e.IsSequence() && e.size()==2) {
                auto s = e[0].as<std::string>();
                auto d = e[1].as<std::string>();
                g.add_edge(s, d);
            }
        }
    }
    return g.finalize();
}

} } } // namespace

