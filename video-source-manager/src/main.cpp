#include "app/source_agent.h"
#include <csignal>
#include <iostream>
#include <thread>
#include <chrono>

static vsm::SourceAgent* g_agent = nullptr;

void signalHandler(int signum) {
  std::cout << "\nReceived signal " << signum << ", shutting down..." << std::endl;
  if (g_agent) g_agent->Stop();
  std::exit(signum);
}

int main(int argc, char* argv[]) {
  std::signal(SIGINT, signalHandler);
  std::string grpc_addr = "0.0.0.0:7070";
  if (argc > 1) grpc_addr = argv[1];
  vsm::SourceAgent agent; g_agent = &agent;
  if (!agent.Start(grpc_addr)) {
    std::cerr << "Failed to start gRPC server at " << grpc_addr << std::endl;
    return -1;
  }
  std::cout << "VSM running at gRPC=" << grpc_addr << ". Press Ctrl+C to stop." << std::endl;
  while (true) std::this_thread::sleep_for(std::chrono::seconds(60));
  return 0;
}
