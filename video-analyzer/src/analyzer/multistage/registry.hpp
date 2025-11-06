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

// 生成唯一的静态变量名，避免同一 CLASS 多次注册时发生重定义
#ifndef VA_MS_CONCAT_INNER
#  define VA_MS_CONCAT_INNER(a,b) a##b
#endif
#ifndef VA_MS_CONCAT
#  define VA_MS_CONCAT(a,b) VA_MS_CONCAT_INNER(a,b)
#endif
#ifdef __COUNTER__
#  define VA_MS_UNIQUE(base) VA_MS_CONCAT(base, __COUNTER__)
#else
#  define VA_MS_UNIQUE(base) VA_MS_CONCAT(base, __LINE__)
#endif

#define MS_REGISTER_NODE(TYPE, CLASS) \
    static bool VA_MS_UNIQUE(__ms_reg_) = [](){ \
        va::analyzer::multistage::NodeRegistry::instance().reg(TYPE, \
            [](const std::unordered_map<std::string,std::string>& cfg){ \
                return std::make_shared<CLASS>(cfg); }); \
        return true; }();

} } } // namespace va::analyzer::multistage

