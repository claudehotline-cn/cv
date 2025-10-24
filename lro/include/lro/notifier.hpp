#pragma once
#include <string>
#include <functional>
#include "lro/runner.hpp"

namespace lro {

struct INotifier {
  virtual ~INotifier() = default;
  // Called by Runner when status changes
  virtual void on_status(const Operation& /*op*/) {}
  // Keepalive tick (e.g., for SSE)
  virtual void on_keepalive(const std::string& /*op_id*/) {}
};

} // namespace lro

