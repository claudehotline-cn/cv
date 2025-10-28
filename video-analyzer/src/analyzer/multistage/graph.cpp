#include "analyzer/multistage/graph.hpp"
#include "core/logger.hpp"
#include <unordered_set>
#include <algorithm>
#include <queue>

namespace va { namespace analyzer { namespace multistage {

int Graph::add_node(const std::string& name, NodePtr node, const std::string& type,
                    const std::unordered_map<std::string,std::string>& cfg) {
    int id = static_cast<int>(nodes_.size());
    nodes_.push_back(NodeEntry{std::move(node), name, type, cfg});
    name2id_[name] = id;
    return id;
}

void Graph::add_edge(const std::string& src, const std::string& dst) {
    auto itS = name2id_.find(src);
    auto itD = name2id_.find(dst);
    if (itS == name2id_.end() || itD == name2id_.end()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "composition")
            << "Graph add_edge ignored: src='" << src << "' dst='" << dst
            << "' (one or both nodes not found at add_edge time)";
        return;
    }
    edges_.push_back(Edge{itS->second, itD->second, std::string(), false, false});
}

void Graph::add_edge_cond(const std::string& src, const std::string& dst,
                          const std::string& attr_key, bool when_not) {
    auto itS = name2id_.find(src);
    auto itD = name2id_.find(dst);
    if (itS == name2id_.end() || itD == name2id_.end()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "composition")
            << "Graph add_edge_cond ignored: src='" << src << "' dst='" << dst
            << "' (one or both nodes not found at add_edge time)";
        return;
    }
    std::string key = attr_key;
    if (key.rfind("attr:", 0) == 0) key = key.substr(5);
    edges_.push_back(Edge{itS->second, itD->second, key, when_not, true});
}

bool Graph::finalize() {
    // Kahn topo sort
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> indeg(n, 0);
    std::vector<std::vector<int>> adj(n);
    for (auto& e : edges_) { indeg[e.to]++; adj[e.from].push_back(e.to); }
    std::queue<int> q;
    for (int i=0;i<n;++i) if (indeg[i]==0) q.push(i);
    topo_.clear(); topo_.reserve(n);
    while (!q.empty()) {
        int u = q.front(); q.pop(); topo_.push_back(u);
        for (int v : adj[u]) { if (--indeg[v]==0) q.push(v); }
    }
    if (static_cast<int>(topo_.size()) != n) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "Graph finalize failed: cycle or unresolved edges (topo.size=" << topo_.size() << "/" << n << ")";
        return false;
    }

    // I/O validation pass: ensure each node's declared inputs are produced by some previous node
    std::unordered_set<std::string> produced;
    // Seed with implicit inputs available in Packet
    produced.insert("frame");
    bool ok = true;
    std::unordered_set<std::string> seen_outputs;
    std::unordered_map<std::string, std::string> output_owner; // key -> node name
    std::unordered_set<std::string> consumed_all;
    for (int id : topo_) {
        const auto& ne = nodes_[id];
        // Inputs check
        for (const auto& key : ne.node->inputs()) {
            if (!key.empty() && !produced.count(key)) {
                VA_LOG_C(::va::core::LogLevel::Error, "composition")
                    << "Graph input missing before node name='" << ne.name << "' type='" << ne.type << "' key='" << key << "'";
                ok = false;
            }
            if (!key.empty()) consumed_all.insert(key);
        }
        // Outputs registration
        for (const auto& key : ne.node->outputs()) {
            if (key.empty()) continue;
            if (seen_outputs.count(key)) {
                VA_LOG_C(::va::core::LogLevel::Warn, "composition")
                    << "Graph output key duplicate: key='" << key << "' at node name='" << ne.name << "' type='" << ne.type << "'";
            }
            produced.insert(key);
            seen_outputs.insert(key);
            output_owner.emplace(key, ne.name);
        }
    }
    if (!ok) {
        VA_LOG_C(::va::core::LogLevel::Error, "composition") << "Graph I/O validation failed.";
        return false;
    }
    // Outputs never consumed (potentially wasted computation)
    for (const auto& kv : output_owner) {
        const auto& key = kv.first; const auto& owner = kv.second;
        if (!consumed_all.count(key)) {
            VA_LOG_C(::va::core::LogLevel::Warn, "composition")
                << "Graph output not consumed: key='" << key << "' produced by node '" << owner << "'";
        }
    }
    return true;
}

static bool attr_truthy(const Attr& a) {
    if (std::holds_alternative<int64_t>(a)) return std::get<int64_t>(a) != 0;
    if (std::holds_alternative<double>(a)) return std::get<double>(a) != 0.0;
    if (std::holds_alternative<float>(a)) return std::get<float>(a) != 0.0f;
    if (std::holds_alternative<std::string>(a)) {
        std::string v = std::get<std::string>(a);
        std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){ return (char)std::tolower(c); });
        return (v=="1"||v=="true"||v=="yes"||v=="on");
    }
    return false;
}

bool Graph::run(Packet& p, NodeContext& ctx) {
    if (!opened_) {
        if (!open_all(ctx)) return false;
    }
    for (int id : topo_) {
        // Conditional gate: if there are incoming conditional edges, require at least one satisfied
        bool has_cond = false, pass = false;
        for (const auto& e : edges_) {
            if (e.to != id || !e.has_cond) continue;
            has_cond = true;
            auto it = p.attrs.find(e.attr_key);
            bool truth = (it != p.attrs.end()) ? attr_truthy(it->second) : false;
            if (e.when_not) truth = !truth;
            if (truth) { pass = true; break; }
        }
        if (has_cond && !pass) {
            continue; // skip this node for this packet
        }
        if (!nodes_[id].node->process(p, ctx)) {
            // 补充上下文：当前可用张量键与形状（最多3项），辅助定位问题
            int shown = 0;
            std::ostringstream os; os << "Graph node failed: name='" << nodes_[id].name << "' type='" << nodes_[id].type << "'";
            if (!p.tensors.empty()) {
                os << " tensors=[";
                for (const auto& kv : p.tensors) {
                    if (shown++ >= 3) { os << "..."; break; }
                    os << kv.first << ":";
                    const auto& tv = kv.second;
                    for (size_t i=0;i<tv.shape.size();++i){ os << (i?"x":""); os << tv.shape[i]; }
                    os << (tv.on_gpu?"(gpu)":"(cpu)") << ",";
                }
                os << "]";
            }
            VA_LOG_C(::va::core::LogLevel::Error, "composition") << os.str();
            return false;
        }
    }
    return true;
}

bool Graph::open_all(NodeContext& ctx) {
    if (opened_) return true;
    // Prefer topological order; fallback to insertion order
    if (!topo_.empty()) {
        for (int id : topo_) {
            if (!nodes_[id].node->open(ctx)) {
                VA_LOG_C(::va::core::LogLevel::Error, "composition") << "Graph node open failed: name='" << nodes_[id].name << "' type='" << nodes_[id].type << "'";
                return false;
            }
        }
    } else {
        for (size_t i = 0; i < nodes_.size(); ++i) {
            if (!nodes_[i].node->open(ctx)) {
                VA_LOG_C(::va::core::LogLevel::Error, "composition") << "Graph node open failed: name='" << nodes_[i].name << "' type='" << nodes_[i].type << "'";
                return false;
            }
        }
    }
    opened_ = true;
    return true;
}

void Graph::close_all(NodeContext& ctx) {
    if (!opened_) return;
    if (!topo_.empty()) {
        for (auto it = topo_.rbegin(); it != topo_.rend(); ++it) {
            nodes_[*it].node->close(ctx);
        }
    } else {
        for (auto it = nodes_.rbegin(); it != nodes_.rend(); ++it) {
            it->node->close(ctx);
        }
    }
    opened_ = false;
}

void Graph::clear() {
    // Best-effort close before clearing
    NodeContext dummy_ctx{};
    close_all(dummy_ctx);
    nodes_.clear(); edges_.clear(); topo_.clear(); name2id_.clear();
}

bool Graph::with_node(const std::string& name,
                      const std::function<bool(NodePtr& node, std::string& type, std::unordered_map<std::string,std::string>& cfg)>& fn) {
    auto it = name2id_.find(name);
    if (it == name2id_.end()) return false;
    auto& ne = nodes_[it->second];
    return fn(ne.node, ne.type, ne.cfg);
}

void Graph::for_each_node(const std::function<void(const std::string& name, const std::string& type,
                                    const std::unordered_map<std::string,std::string>& cfg)>& fn) const {
    for (const auto& ne : nodes_) {
        fn(ne.name, ne.type, ne.cfg);
    }
}

} } } // namespace
