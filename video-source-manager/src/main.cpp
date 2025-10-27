#include "app/source_agent.h"
#include "app/config.hpp"
#include <csignal>
#include <iostream>
#include <thread>
#include <chrono>
#include <filesystem>

static vsm::SourceAgent* g_agent = nullptr;

void signalHandler(int signum) {
  std::cout << "\nReceived signal " << signum << ", shutting down..." << std::endl;
  if (g_agent) g_agent->Stop();
  std::exit(signum);
}

int main(int argc, char* argv[]) {
  std::signal(SIGINT, signalHandler);
  std::string grpc_addr = "0.0.0.0:7070";
  // 支持两种启动方式：
  // 1) 参数为配置目录：读取 app.yaml 并使用其中的 server/tls 配置（推荐）
  // 2) 参数为监听地址字符串，如 0.0.0.0:7070（仅用于临时场景）
  if (argc > 1) {
    std::string arg1 = argv[1];
    std::error_code ec;
    auto p = std::filesystem::path(arg1);
    if (std::filesystem::is_directory(p, ec)) {
      vsm::app::AppConfig cfg;
      std::string err;
      if (!vsm::app::LoadConfigFromDir(arg1, &cfg, &err)) {
        std::cerr << "Failed to load VSM config: " << err << std::endl;
        return -2;
      }
      vsm::SourceAgent agent2; g_agent = &agent2;
      if (!agent2.Start(cfg)) {
        std::cerr << "Failed to start gRPC server at " << cfg.grpc_listen << std::endl;
        return -1;
      }
      std::cout << "VSM running at gRPC=" << cfg.grpc_listen << ". Press Ctrl+C to stop." << std::endl;
      while (true) std::this_thread::sleep_for(std::chrono::seconds(60));
      return 0;
    } else {
      grpc_addr = arg1; // 传参：直接作为地址
    }
  }
  vsm::SourceAgent agent; g_agent = &agent;
  if (!agent.Start(grpc_addr)) {
    std::cerr << "Failed to start gRPC server at " << grpc_addr << std::endl;
    return -1;
  }
  std::cout << "VSM running at gRPC=" << grpc_addr << ". Press Ctrl+C to stop." << std::endl;
  while (true) std::this_thread::sleep_for(std::chrono::seconds(60));
  return 0;
}

