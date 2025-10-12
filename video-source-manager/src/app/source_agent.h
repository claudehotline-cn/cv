#pragma once

#include <memory>
#include <string>

namespace vsm { class SourceController; }
namespace vsm::rpc { class GrpcServer; }
namespace vsm::metrics { class MetricsExporter; }

namespace vsm {

class SourceAgent {
public:
  SourceAgent();
  ~SourceAgent();
  bool Start(const std::string& grpc_addr);
  void Stop();
private:
  std::unique_ptr<SourceController> controller_;
  std::unique_ptr<rpc::GrpcServer> grpc_;
  std::unique_ptr<metrics::MetricsExporter> metrics_;
};

} // namespace vsm
