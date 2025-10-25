#include <iostream>
#include <string>
#include <thread>
#include <chrono>

#include "controlplain/config.hpp"

namespace controlplain { bool quick_probe_va(const std::string&); bool quick_probe_vsm(const std::string&); }

int main(int argc, char** argv) {
  using namespace controlplain;
  std::string cfgDir = "controlplain/config";
  if (argc >= 2) cfgDir = argv[1];

  AppConfig cfg;
  std::string err;
  if (!load_config(cfgDir, &cfg, &err)) {
    std::cerr << "[controlplain] load_config failed: " << err << std::endl;
    return 1;
  }
  std::cout << "[controlplain] listen=" << cfg.http_listen
            << " va=" << cfg.va_addr << " vsm=" << cfg.vsm_addr << std::endl;

  // Quick gRPC probes (best-effort)
  try { quick_probe_va(cfg.va_addr); } catch (...) {}
  try { quick_probe_vsm(cfg.vsm_addr); } catch (...) {}

  // Placeholder: HTTP server to be implemented in next steps. Here we keep process alive.
  std::cout << "[controlplain] started (skeleton). Press Ctrl+C to exit." << std::endl;
  while (true) std::this_thread::sleep_for(std::chrono::seconds(60));
  return 0;
}

