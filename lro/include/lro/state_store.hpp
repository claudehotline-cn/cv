#pragma once
#include <string>
#include <optional>
#include <unordered_map>
#include <mutex>
#include <memory>
#include "lro/runner.hpp"

namespace lro {

struct IStateStore {
  virtual ~IStateStore() = default;
  virtual bool put(const Operation& op) = 0;
  virtual std::optional<Operation> get(const std::string& id) const = 0;
  virtual bool update(const Operation& op) = 0;
};

// Minimal in-memory store (header-only skeleton)
class MemoryStore : public IStateStore {
public:
  bool put(const Operation& op) override { std::lock_guard<std::mutex> lk(mu_); return map_.emplace(op.id, op).second; }
  std::optional<Operation> get(const std::string& id) const override {
    std::lock_guard<std::mutex> lk(mu_); auto it = map_.find(id); if (it==map_.end()) return std::nullopt; return it->second; }
  bool update(const Operation& op) override { std::lock_guard<std::mutex> lk(mu_); auto it=map_.find(op.id); if(it==map_.end()) return false; it->second=op; return true; }
private:
  mutable std::mutex mu_;
  std::unordered_map<std::string, Operation> map_;
};

// WAL adapter interface (bridge to project-specific WAL)
struct IWalAdapter {
  virtual ~IWalAdapter() = default;
  virtual void on_enqueue(const Operation& /*op*/) {}
  virtual void on_complete(const Operation& /*op*/) {}
};

} // namespace lro

