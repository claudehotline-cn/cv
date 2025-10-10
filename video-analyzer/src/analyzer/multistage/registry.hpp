#pragma once

#include "interfaces.hpp"
#include <functional>

namespace va { namespace analyzer { namespace multistage {

using NodeCreateFn = std::function<NodePtr(const std::unordered_map<std::string,std::string>&)>;

class NodeRegistry {
public:
    static NodeRegistry& instance();
    void reg(const std::string& type, NodeCreateFn fn);
    NodePtr create(const std::string& type,
                   const std::unordered_map<std::string,std::string>& cfg) const;
private:
    std::unordered_map<std::string, NodeCreateFn> map_;
};

#define MS_REGISTER_NODE(TYPE, CLASS) \
    static bool __ms_reg_##CLASS = [](){ \
        va::analyzer::multistage::NodeRegistry::instance().reg(TYPE, \
            [](const std::unordered_map<std::string,std::string>& cfg){ \
                return std::make_shared<CLASS>(cfg); }); \
        return true; }();

} } } // namespace va::analyzer::multistage

