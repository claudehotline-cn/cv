#include "analyzer/multistage/registry.hpp"
#include <stdexcept>

namespace va { namespace analyzer { namespace multistage {

NodeRegistry& NodeRegistry::instance() {
    static NodeRegistry r; return r;
}

void NodeRegistry::reg(const std::string& t, NodeCreateFn fn) {
    map_[t] = std::move(fn);
}

NodePtr NodeRegistry::create(const std::string& t, const std::unordered_map<std::string,std::string>& cfg) const {
    auto it = map_.find(t);
    if (it == map_.end()) throw std::runtime_error("Unknown node type: " + t);
    return it->second(cfg);
}

} } } // namespace

