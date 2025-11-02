#pragma once
#include <memory>
#include <functional>
#include <string>
#include <mutex>
#include <unordered_map>
#include "lro/operation.h"

namespace lro {

// 状态存储 SPI（可替换为 Redis/DB/WAL）
struct IStateStore {
    virtual ~IStateStore() = default;
    virtual bool put(const std::shared_ptr<Operation>& op) = 0;
    virtual std::shared_ptr<Operation> get(const std::string& id) = 0;
    virtual std::shared_ptr<Operation> getByKey(const std::string& key) = 0; // 幂等键
    virtual bool update(const std::shared_ptr<Operation>& op) = 0;
    // 只读遍历当前操作快照
    virtual void for_each(const std::function<void(const std::shared_ptr<Operation>&)>& fn) const = 0;
};

// 内存存储实现（编译库内提供）
class MemoryStore : public IStateStore {
public:
    bool put(const std::shared_ptr<Operation>& op) override {
        std::lock_guard<std::mutex> lk(m_);
        if (!op) return false;
        if (by_id_.count(op->id)) return false;
        by_id_[op->id] = op;
        if (!op->idempotency_key.empty()) by_key_[op->idempotency_key] = op;
        return true;
    }
    std::shared_ptr<Operation> get(const std::string& id) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_id_.find(id);
        return it==by_id_.end()? nullptr : it->second;
    }
    std::shared_ptr<Operation> getByKey(const std::string& key) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_key_.find(key);
        return it==by_key_.end()? nullptr : it->second;
    }
    bool update(const std::shared_ptr<Operation>& op) override {
        std::lock_guard<std::mutex> lk(m_);
        auto it = by_id_.find(op->id);
        if (it==by_id_.end()) return false;
        it->second = op;
        if (!op->idempotency_key.empty()) by_key_[op->idempotency_key] = op;
        return true;
    }
    void for_each(const std::function<void(const std::shared_ptr<Operation>&)>& fn) const override {
        std::lock_guard<std::mutex> lk(m_);
        for (const auto& kv : by_id_) { fn(kv.second); }
    }
private:
    mutable std::mutex m_;
    std::unordered_map<std::string, std::shared_ptr<Operation>> by_id_;
    std::unordered_map<std::string, std::shared_ptr<Operation>> by_key_;
};

// 便捷工厂
std::shared_ptr<IStateStore> make_memory_store();

} // namespace lro

