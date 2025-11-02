#pragma once

#include "interfaces.hpp"
#include <unordered_map>
#include <functional>

namespace va { namespace analyzer { namespace multistage {

  class Graph {
  public:
    int add_node(const std::string& name, NodePtr node, const std::string& type,
                 const std::unordered_map<std::string,std::string>& cfg);
    void add_edge(const std::string& src, const std::string& dst);
    void add_edge_cond(const std::string& src, const std::string& dst,
                       const std::string& attr_key, bool when_not);
    bool finalize();
    bool run(Packet& p, NodeContext& ctx);
    // Lifecycle management for nodes (idempotent open)
    bool open_all(NodeContext& ctx);
    void close_all(NodeContext& ctx);
    void clear();
    // Visit a node by name and allow mutation; returns false if node missing or fn returns false
    bool with_node(const std::string& name,
                   const std::function<bool(NodePtr& node, std::string& type, std::unordered_map<std::string,std::string>& cfg)>& fn);
    // Visit all nodes (read-only for external users; cfg is const here)
    void for_each_node(const std::function<void(const std::string& name, const std::string& type,
                                               const std::unordered_map<std::string,std::string>& cfg)>& fn) const;
  private:
    struct NodeEntry { NodePtr node; std::string name; std::string type; std::unordered_map<std::string,std::string> cfg; };
    struct Edge { int from; int to; std::string attr_key; bool when_not {false}; bool has_cond {false}; };
    std::vector<NodeEntry> nodes_;
    std::vector<Edge> edges_;
    std::vector<int> topo_;
    std::unordered_map<std::string,int> name2id_;
    bool opened_ {false};
};

} } } // namespace
