#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>

namespace va { namespace control {

struct Status {
    bool ok_ {true};
    std::string msg_;
    static Status OK() { return {true, {}}; }
    static Status InvalidArgument(std::string m) { return {false, std::string("invalid: ")+m}; }
    static Status NotFound(std::string m) { return {false, std::string("not_found: ")+m}; }
    static Status Internal(std::string m) { return {false, std::string("internal: ")+m}; }
    bool ok() const { return ok_; }
    const std::string& message() const { return msg_; }
};

// 轻量泛型句柄（带自定义删除器），用于跨模块管理具体实现类型
struct OpaquePtr {
    void* ptr {nullptr};
    void (*deleter)(void*) {nullptr};
    OpaquePtr() = default;
    OpaquePtr(void* p, void(*d)(void*)) : ptr(p), deleter(d) {}
    OpaquePtr(const OpaquePtr&) = delete;
    OpaquePtr& operator=(const OpaquePtr&) = delete;
    OpaquePtr(OpaquePtr&& o) noexcept : ptr(o.ptr), deleter(o.deleter) { o.ptr=nullptr; o.deleter=nullptr; }
    OpaquePtr& operator=(OpaquePtr&& o) noexcept { if (this!=&o){ reset(); ptr=o.ptr; deleter=o.deleter; o.ptr=nullptr; o.deleter=nullptr; } return *this; }
    ~OpaquePtr() { reset(); }
    void reset(){ if (ptr && deleter) deleter(ptr); ptr=nullptr; deleter=nullptr; }
    void* get() const { return ptr; }
};

// 轻量 Pipeline 规范占位（后续可由 proto/json 反序列化填充）
struct PlainPipelineSpec {
    std::string name;         // pipeline 名称
    std::string graph_id;     // 可选：在 config/graphs 下解析
    std::string yaml_path;    // 可选：绝对/相对 YAML 路径
    std::string revision;
    // M3: 模板与治理元信息
    std::string template_id;
    std::unordered_map<std::string,std::string> overrides;
    std::string project;
    std::vector<std::string> tags;     // 版本/修订
};

class IExecutor {
public:
    virtual ~IExecutor() = default;
    virtual bool Start(std::string* err) = 0;
    virtual void Stop() = 0;
    virtual Status Drain(int timeout_sec) = 0;
    virtual Status HotSwapModel(const std::string& node, const std::string& uri) = 0;
    virtual std::string CollectStatusJson() = 0;
};

class IGraphAdapter {
public:
    virtual ~IGraphAdapter() = default;
    // 依据 PlainPipelineSpec 构建图（后续可扩展为 proto->Graph）
    virtual OpaquePtr BuildGraph(const PlainPipelineSpec& spec, std::string* err) = 0;
    virtual std::unique_ptr<IExecutor> CreateExecutor(void* graph, std::string* err) = 0;
};

} } // namespace va::control
