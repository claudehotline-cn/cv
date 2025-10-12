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
        const std::string key = it.first.as<std::string>();
        const YAML::Node& val = it.second;
        try {
            if (val.IsSequence()) {
                // Join sequence as comma-separated for keys like 'outs'
                std::string joined;
                for (std::size_t i=0;i<val.size();++i) {
                    if (i) joined += ",";
                    joined += val[i].as<std::string>("");
                }
                m[key] = joined;
            } else if (val.IsScalar()) {
                m[key] = val.as<std::string>("");
            } else if (val.IsMap()) {
                // Best-effort: flatten one-level map as key1:val1;key2:val2
                std::string flat; bool first=true;
                for (auto kv : val) {
                    if (!first) flat += ";"; first=false;
                    flat += kv.first.as<std::string>("");
                    flat += ":";
                    flat += kv.second.as<std::string>("");
                }
                m[key] = flat;
            } else {
                m[key] = "";
            }
        } catch (...) {
            m[key] = "";
        }
    }
    return m;
}

namespace {
static void apply_param_overrides_for_node(
    std::unordered_map<std::string,std::string>& params,
    const std::string& node_name,
    const std::string& node_type,
    const std::unordered_map<std::string,std::string>& overrides) {
    const std::string p_node = std::string("node.") + node_name + ".";
    const std::string p_type = std::string("type:") + node_type + ".";
    for (const auto& kv : overrides) {
        const auto& k = kv.first;
        if (k.rfind(p_node, 0) == 0) {
            auto sub = k.substr(p_node.size());
            if (!sub.empty()) params[sub] = kv.second;
        } else if (k.rfind(p_type, 0) == 0) {
            auto sub = k.substr(p_type.size());
            if (!sub.empty()) params[sub] = kv.second;
        }
    }
}
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
            if (e.IsSequence() && (e.size()==2 || e.size()==3)) {
                auto s = e[0].as<std::string>();
                auto d = e[1].as<std::string>();
                if (e.size()==2) {
                    g.add_edge(s, d);
                } else if (e[2].IsMap()) {
                    auto cond = e[2];
                    const bool has_when = static_cast<bool>(cond["when"]);
                    const bool has_when_not = static_cast<bool>(cond["when_not"]);
                    if (has_when && has_when_not) {
                        VA_LOG_C(::va::core::LogLevel::Warn, "composition")
                            << "edge ('" << s << "'->'" << d << "') has both when and when_not; prioritizing 'when'";
                    }
                    if (has_when) {
                        auto k = cond["when"].as<std::string>("");
                        g.add_edge_cond(s, d, k, /*when_not*/false);
                    } else if (has_when_not) {
                        auto k = cond["when_not"].as<std::string>("");
                        g.add_edge_cond(s, d, k, /*when_not*/true);
                    } else {
                        g.add_edge(s, d);
                    }
                } else {
                    g.add_edge(s, d);
                }
            }
        }
    }
    if (!g.finalize()) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML graph finalize failed (cycle or missing nodes): " << file;
        return false;
    }
    return true;
}

bool build_graph_from_yaml_with_overrides(const std::string& file,
    const std::unordered_map<std::string,std::string>& overrides,
    Graph& g) {
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
        apply_param_overrides_for_node(params, name, type, overrides);
        auto node = NodeRegistry::instance().create(type, params);
        int id = g.add_node(name, node, type, params);
        name2id[name] = id;
    }
    // Edges
    auto edges = ms["edges"];
    if (edges && edges.IsSequence()) {
        for (auto e : edges) {
            if (e.IsSequence() && (e.size()==2 || e.size()==3)) {
                auto s = e[0].as<std::string>();
                auto d = e[1].as<std::string>();
                if (e.size()==2) {
                    g.add_edge(s, d);
                } else if (e[2].IsMap()) {
                    auto cond = e[2];
                    const bool has_when = static_cast<bool>(cond["when"]);
                    const bool has_when_not = static_cast<bool>(cond["when_not"]);
                    if (has_when && has_when_not) {
                        VA_LOG_C(::va::core::LogLevel::Warn, "composition")
                            << "edge ('" << s << "'->'" << d << "') has both when and when_not; prioritizing 'when'";
                    }
                    if (has_when) {
                        auto k = cond["when"].as<std::string>("");
                        g.add_edge_cond(s, d, k, /*when_not*/false);
                    } else if (has_when_not) {
                        auto k = cond["when_not"].as<std::string>("");
                        g.add_edge_cond(s, d, k, /*when_not*/true);
                    } else {
                        g.add_edge(s, d);
                    }
                } else {
                    g.add_edge(s, d);
                }
            }
        }
    }
    if (!g.finalize()) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "YAML graph finalize failed: " << file;
        return false;
    }
    return true;
}

} } } // namespace
