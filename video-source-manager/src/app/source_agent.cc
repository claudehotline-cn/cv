#include "app/source_agent.h"
#include "app/controller/source_controller.h"
#include "app/rpc/grpc_server.h"
#include "app/metrics/metrics_exporter.h"
#include <sstream>
#include <string>

namespace vsm {

SourceAgent::SourceAgent() = default;
SourceAgent::~SourceAgent() { Stop(); }

bool SourceAgent::Start(const std::string& grpc_addr) {
  controller_ = std::make_unique<SourceController>();
  grpc_ = std::make_unique<rpc::GrpcServer>(*controller_, grpc_addr);
  // Metrics exporter builds /metrics on demand from controller stats
  metrics_ = std::make_unique<metrics::MetricsExporter>(9101, [this]() {
    std::ostringstream out;
    out << "# HELP vsm_stream_up 1 if stream session is running\n# TYPE vsm_stream_up gauge\n";
    out << "# HELP vsm_stream_fps Frames per second\n# TYPE vsm_stream_fps gauge\n";
    for (const auto& s : controller_->Collect()) {
      int up = (s.phase == "Ready") ? 1 : 0;
      out << "vsm_stream_up{attach_id=\"" << s.attach_id << "\"} " << up << "\n";
      out << "vsm_stream_fps{attach_id=\"" << s.attach_id << "\"} " << s.fps << "\n";
    }
    return out.str();
  });
  metrics_->Start();
  return grpc_->Start();
}

void SourceAgent::Stop() {
  if (metrics_) { metrics_->Stop(); metrics_.reset(); }
  if (grpc_) { grpc_->Stop(); grpc_.reset(); }
  controller_.reset();
}

} // namespace vsm
