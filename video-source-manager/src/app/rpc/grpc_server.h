#pragma once

#include <memory>
#include <string>

namespace vsm { class SourceController; }

namespace vsm::rpc {

class GrpcServer {
public:
  GrpcServer(SourceController& ctl, std::string addr);
  ~GrpcServer();
  bool Start();
  void Stop();
private:
  struct Impl; std::unique_ptr<Impl> impl_;
};

} // namespace vsm::rpc

