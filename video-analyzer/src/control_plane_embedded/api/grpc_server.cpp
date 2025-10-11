#include "control_plane_embedded/api/grpc_server.hpp"
#include "control_plane_embedded/controllers/pipeline_controller.hpp"
#include "control_plane_embedded/interfaces.hpp"

namespace va { namespace control {

#ifdef USE_GRPC
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "pipeline.pb.h"

class AnalyzerControlServiceImpl final : public va::v1::AnalyzerControl::Service {
public:
    explicit AnalyzerControlServiceImpl(PipelineController* ctl) : ctl_(ctl) {}
    ::grpc::Status ApplyPipeline(::grpc::ServerContext*, const va::v1::ApplyPipelineRequest* req,
                                 va::v1::ApplyPipelineReply* resp) override {
        if (!ctl_) { resp->set_accepted(false); resp->set_msg("no controller"); return ::grpc::Status::OK; }
        PlainPipelineSpec spec;
        spec.name = req->pipeline_name();
        spec.revision = req->revision();
        if (!req->spec().graph_id().empty()) spec.graph_id = req->spec().graph_id();
        if (!req->spec().yaml_path().empty()) spec.yaml_path = req->spec().yaml_path();
        if (spec.graph_id.empty() && spec.yaml_path.empty()) {
            // 结构化 pipeline 还未适配，暂不支持
            resp->set_accepted(false);
            resp->set_msg("only graph_id/yaml_path supported in this phase");
            return ::grpc::Status::OK;
        }
        auto st = ctl_->Apply(spec);
        resp->set_accepted(st.ok()); resp->set_msg(st.message());
        return ::grpc::Status::OK;
    }
    ::grpc::Status RemovePipeline(::grpc::ServerContext*, const va::v1::RemovePipelineRequest* req,
                                  va::v1::RemovePipelineReply* resp) override {
        auto st = ctl_->Remove(req->pipeline_name());
        resp->set_removed(st.ok()); resp->set_msg(st.message());
        return ::grpc::Status::OK;
    }
    ::grpc::Status HotSwapModel(::grpc::ServerContext*, const va::v1::HotSwapModelRequest* req,
                                va::v1::HotSwapModelReply* resp) override {
        auto st = ctl_->HotSwapModel(req->pipeline_name(), req->node(), req->model_uri());
        resp->set_ok(st.ok()); resp->set_msg(st.message());
        return ::grpc::Status::OK;
    }
    ::grpc::Status Drain(::grpc::ServerContext*, const va::v1::DrainRequest* req,
                         va::v1::DrainReply* resp) override {
        auto st = ctl_->Drain(req->pipeline_name(), req->timeout_sec());
        resp->set_drained(st.ok());
        return ::grpc::Status::OK;
    }
    ::grpc::Status GetStatus(::grpc::ServerContext*, const va::v1::GetStatusRequest* req,
                             va::v1::GetStatusReply* resp) override {
        resp->set_phase("Unknown");
        resp->set_metrics_json(ctl_? ctl_->GetStatus(req->pipeline_name()) : std::string("{}"));
        return ::grpc::Status::OK;
    }
private:
    PipelineController* ctl_ {nullptr};
};

struct GrpcServerBundle { AnalyzerControlServiceImpl* svc {nullptr}; std::unique_ptr<grpc::Server> server; };

OpaquePtr StartGrpcServer(const std::string& addr, AnalyzerControlService*) {
    (void)addr; return {}; // unused overload
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl) {
    auto* svc = new AnalyzerControlServiceImpl(ctl);
    grpc::ServerBuilder b;
    b.AddListeningPort(addr, grpc::InsecureServerCredentials());
    b.RegisterService(svc);
    std::unique_ptr<grpc::Server> server = b.BuildAndStart();
    if (!server) { delete svc; return {}; }
    auto* bundle = new GrpcServerBundle{svc, std::move(server)};
    return OpaquePtr{bundle, [](void* p){ auto* w = reinterpret_cast<GrpcServerBundle*>(p); if (w){ if (w->server) w->server->Shutdown(); delete w->svc; delete w; } }};
}

#else

OpaquePtr StartGrpcServer(const std::string&, AnalyzerControlService*) { return {}; }
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController*) { (void)addr; return {}; }

#endif

} } // namespace
