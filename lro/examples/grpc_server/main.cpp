#include <iostream>
#include <thread>
#include <chrono>
#include <memory>
#include <grpcpp/grpcpp.h>
#include "lro/runner.h"
#include "lro/state_store.h"

// Declarations from server.cpp
namespace lro { namespace rpcimpl {
  std::unique_ptr<grpc::Server> start_grpc_server(const std::string& addr, lro::Runner* runner);
}} // ns

int main() {
  lro::RunnerConfig cfg; cfg.store = lro::make_memory_store();
  lro::Runner runner(cfg);
  // Minimal step to demonstrate async behavior
  runner.addStep({"prepare", [](std::shared_ptr<lro::Operation>& op){ op->phase = "preparing"; std::this_thread::sleep_for(std::chrono::milliseconds(5)); }, lro::Step::IO, 10});
  try {
    auto server = lro::rpcimpl::start_grpc_server("0.0.0.0:50070", &runner);
    if (server) {
      std::cout << "example_grpc started on 0.0.0.0:50070 (demo run)" << std::endl;
      // Demo: run briefly then shutdown
      std::this_thread::sleep_for(std::chrono::milliseconds(50));
      server->Shutdown();
      std::cout << "example_grpc shutdown" << std::endl;
    } else {
      std::cout << "example_grpc build-only (server not started)" << std::endl;
    }
  } catch (...) {
    std::cout << "example_grpc failed to start (build-only)" << std::endl;
  }
  return 0;
}
