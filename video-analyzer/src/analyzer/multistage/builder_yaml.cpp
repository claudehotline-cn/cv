#include "analyzer/multistage/builder_yaml.hpp"
#include "analyzer/multistage/registry.hpp"
#include "core/logger.hpp"
#include <yaml-cpp/yaml.h>
#include <system_error>

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
    YAML::Node root;
    try {
        root = YAML::LoadFile(file);
    } catch (const std::exception& ex) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML load failed: " << file << " error=" << ex.what();
        return false;
    }
    YAML::Node ms = root["analyzer"]["multistage"];
    if (!ms) ms = root["multistage"]; // allow top-level
    if (!ms) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML missing analyzer.multistage: " << file;
        return false;
    }
    std::unordered_map<std::string,int> name2id;
    // Nodes
    auto nodes = ms["nodes"];
    if (!nodes || !nodes.IsSequence()) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML nodes not a sequence: " << file;
        return false;
    }
    for (auto nd : nodes) {
        if (!nd["name"] || !nd["type"]) {
            VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML node missing name/type: " << file;
            return false;
        }
        std::string name;
        std::string type;
        try { name = nd["name"].as<std::string>(); type = nd["type"].as<std::string>(); }
        catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML node name/type not string: " << file;
            return false;
        }
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
    if (!g.finalize()) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML graph finalize failed (cycle or missing nodes): " << file;
        return false;
    }
    return true;
}

} } } // namespace
