#pragma once
#include <functional>
#include <string>

namespace lro { class Runner; }

namespace lro::rest {

// Minimal placeholder for wiring Runner to a REST router
// Users can integrate with their server by mapping:
// POST /operations -> runner.create
// GET /operations/{id} -> runner.get
// DELETE /operations/{id} -> runner.cancel
// GET /operations/{id}/events -> runner.watch
struct RouterHooks {
  std::function<void(const std::string& path,
                     std::function<std::string(const std::string& body)>)> post;
  std::function<void(const std::string& path,
                     std::function<std::string(const std::string& id)>)> get;
  std::function<void(const std::string& path,
                     std::function<std::string(const std::string& id)>)> del;
  // Note: SSE/WS stream hook omitted in skeleton
};

inline void register_basic_routes(RouterHooks&, Runner*) {
  // left empty intentionally; users should implement routing in their server
}

} // namespace lro::rest

