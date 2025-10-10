#pragma once

#include "interfaces.hpp"
#include <unordered_map>

namespace va { namespace analyzer { namespace multistage {

class Graph {
public:
    int add_node(const std::string& name, NodePtr node, const std::string& type,
                 const std::unordered_map<std::string,std::string>& cfg);
    void add_edge(const std::string& src, const std::string& dst);
    bool finalize();
    bool run(Packet& p, NodeContext& ctx);
    void clear();
private:
    struct NodeEntry { NodePtr node; std::string name; std::string type; std::unordered_map<std::string,std::string> cfg; };
    std::vector<NodeEntry> nodes_;
    std::vector<std::pair<int,int>> edges_;
    std::vector<int> topo_;
    std::unordered_map<std::string,int> name2id_;
};

} } } // namespace

