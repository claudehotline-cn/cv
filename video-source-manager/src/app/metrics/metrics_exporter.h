#pragma once

#include <atomic>
#include <functional>
#include <string>
#include <thread>

namespace vsm::metrics {

class MetricsExporter {
public:
  using BuilderFn = std::function<std::string()>;

  MetricsExporter(int port, BuilderFn builder);
  ~MetricsExporter();

  bool Start();
  void Stop();

private:
  void ServerLoop();
  void WakeAccept();

  int port_;
  BuilderFn builder_;
  std::atomic<bool> running_{false};
  std::thread th_;
  // server socket for graceful shutdown
  int server_fd_{-1};
};

} // namespace vsm::metrics
