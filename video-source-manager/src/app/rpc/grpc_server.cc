#include "app/rpc/grpc_server.h"
#include "app/controller/source_controller.h"

#if defined(USE_GRPC)
#include <grpcpp/grpcpp.h>
#include "source_control.grpc.pb.h"
#endif

namespace vsm::rpc {

struct GrpcServer::Impl {
  vsm::SourceController& ctl;
  std::string addr;
#if defined(USE_GRPC)
  class ServiceImpl final : public vsm::v1::SourceControl::Service {
  public:
    explicit ServiceImpl(vsm::SourceController& c) : ctl_(c) {}
    ::grpc::Status Attach(::grpc::ServerContext*, const vsm::v1::AttachRequest* req,
                          vsm::v1::AttachReply* resp) override {
      std::unordered_map<std::string,std::string> opts(req->options().begin(), req->options().end());
      std::string err; bool ok = ctl_.Attach(req->attach_id(), req->source_uri(), req->pipeline_id(), opts, &err);
      resp->set_accepted(ok); resp->set_msg(ok? std::string("") : err); return ::grpc::Status::OK;
    }
    ::grpc::Status Detach(::grpc::ServerContext*, const vsm::v1::DetachRequest* req,
                          vsm::v1::DetachReply* resp) override {
      std::string err; bool ok = ctl_.Detach(req->attach_id(), &err);
      resp->set_removed(ok); resp->set_msg(ok? std::string("") : err); return ::grpc::Status::OK;
    }
    ::grpc::Status GetHealth(::grpc::ServerContext*, const vsm::v1::GetHealthRequest*,
                             vsm::v1::GetHealthReply* resp) override {
      for (auto s : ctl_.Collect()) {
        auto* it = resp->add_streams();
        it->set_attach_id(s.attach_id); it->set_fps(s.fps); it->set_rtt_ms(s.rtt_ms);
        it->set_jitter_ms(s.jitter_ms); it->set_loss_pct(s.loss_pct); it->set_phase(s.phase);
      }
      return ::grpc::Status::OK;
    }
  private:
    vsm::SourceController& ctl_;
  };
  std::unique_ptr<grpc::Server> server;
  ServiceImpl* service {nullptr};
#endif
  explicit Impl(vsm::SourceController& c, std::string a) : ctl(c), addr(std::move(a)) {}
};

GrpcServer::GrpcServer(vsm::SourceController& ctl, std::string addr)
  : impl_(std::make_unique<Impl>(ctl, std::move(addr))) {}
GrpcServer::~GrpcServer() { Stop(); }

bool GrpcServer::Start() {
#if defined(USE_GRPC)
  impl_->service = new Impl::ServiceImpl(impl_->ctl);
  grpc::ServerBuilder b; b.AddListeningPort(impl_->addr, grpc::InsecureServerCredentials());
  b.RegisterService(impl_->service); impl_->server = b.BuildAndStart();
  return (bool)impl_->server;
#else
  (void)impl_;
  return true;
#endif
}

void GrpcServer::Stop() {
#if defined(USE_GRPC)
  if (impl_->server) { impl_->server->Shutdown(); impl_->server.reset(); }
  if (impl_->service) { delete impl_->service; impl_->service=nullptr; }
#endif
}

} // namespace vsm::rpc

