#include "analyzer/multistage/graph.hpp"
#include "core/logger.hpp"
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
        return;
    }
    edges_.emplace_back(itS->second, itD->second);
}

bool Graph::finalize() {
    // Kahn topo sort
    const int n = static_cast<int>(nodes_.size());
    std::vector<int> indeg(n, 0);
    std::vector<std::vector<int>> adj(n);
    for (auto& e : edges_) { indeg[e.second]++; adj[e.first].push_back(e.second); }
    std::queue<int> q;
    for (int i=0;i<n;++i) if (indeg[i]==0) q.push(i);
    topo_.clear(); topo_.reserve(n);
    while (!q.empty()) {
        int u = q.front(); q.pop(); topo_.push_back(u);
        for (int v : adj[u]) { if (--indeg[v]==0) q.push(v); }
    }
    return static_cast<int>(topo_.size()) == n;
}

bool Graph::run(Packet& p, NodeContext& ctx) {
    for (int id : topo_) {
        if (!nodes_[id].node->process(p, ctx)) return false;
    }
    return true;
}

void Graph::clear() {
    nodes_.clear(); edges_.clear(); topo_.clear(); name2id_.clear();
}

} } } // namespace

