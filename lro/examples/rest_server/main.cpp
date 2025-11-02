#include <iostream>
#include <map>
#include <functional>
#include <string>
#include <memory>
#include <thread>
#include <chrono>

#include "lro/runner.h"
#include "lro/state_store.h"
#include "lro/adapters/rest_simple.h"

// A tiny in-process router that just stores handlers and allows invoking them.
struct SimpleRouter {
  std::map<std::string, std::function<std::string(const std::string&)>> post_map;
  std::map<std::string, std::function<std::string(const std::string&)>> get_map;
  std::map<std::string, std::function<std::string(const std::string&)>> del_map;

  lro::rest::RouterHooks hooks() {
    lro::rest::RouterHooks h;
    h.post = [&](const std::string& path, std::function<std::string(const std::string&)> cb){ post_map[path]=std::move(cb); };
    h.get  = [&](const std::string& path, std::function<std::string(const std::string&)> cb){ get_map[path]=std::move(cb); };
    h.del  = [&](const std::string& path, std::function<std::string(const std::string&)> cb){ del_map[path]=std::move(cb); };
    return h;
  }
  std::string POST(const std::string& path, const std::string& body) { return post_map.at(path)(body); }
  std::string GET(const std::string& path, const std::string& id)   { return get_map.at(path)(id); }
  std::string DEL(const std::string& path, const std::string& id)   { return del_map.at(path)(id); }
};

int main() {
  // Create runner with memory store and a sample async step.
  lro::RunnerConfig cfg; cfg.store = lro::make_memory_store();
  lro::Runner runner(cfg);
  runner.addStep({"prepare", [](std::shared_ptr<lro::Operation>& op){ op->phase = "preparing"; std::this_thread::sleep_for(std::chrono::milliseconds(10)); }, lro::Step::IO, 10});
  runner.addStep({"work",    [](std::shared_ptr<lro::Operation>& op){ op->phase = "working";   std::this_thread::sleep_for(std::chrono::milliseconds(10)); }, lro::Step::Heavy, 50});

  // Wire simple router
  SimpleRouter router;
  auto hooks = router.hooks();
  lro::rest::register_basic_routes(hooks, &runner);

  // Demo flow (no real HTTP): POST -> GET -> DELETE
  std::string body = "{\"stream_id\":\"demo\",\"profile\":\"p\",\"idempotency_key\":\"demo:1\"}";
  auto resp_create = router.POST("/operations", body);
  std::cout << "CREATE: " << resp_create << std::endl;

  // Extract id from crude JSON (demo only)
  auto q = resp_create.find("\"id\":\"");
  std::string id;
  if (q != std::string::npos) {
    auto s = q + 6; auto e = resp_create.find('"', s); id = resp_create.substr(s, e-s);
  }
  auto resp_get = router.GET("/operations", id);
  std::cout << "GET:    " << resp_get << std::endl;

  auto resp_del = router.DEL("/operations", id);
  std::cout << "DELETE: " << resp_del << std::endl;
  return 0;
}

