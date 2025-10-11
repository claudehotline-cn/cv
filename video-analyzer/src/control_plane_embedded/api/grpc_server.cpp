#include "control_plane_embedded/api/grpc_server.hpp"
#include "control_plane_embedded/controllers/pipeline_controller.hpp"

namespace va { namespace control {

OpaquePtr StartGrpcServer(const std::string&, AnalyzerControlService*) {
    // 未集成 gRPC，返回空句柄
    return {};
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* /*ctl*/) {
    (void)addr;
    return {};
}

} } // namespace
