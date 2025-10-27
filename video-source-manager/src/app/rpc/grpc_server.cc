#include "app/rpc/grpc_server.h"
#include "app/controller/source_controller.h"
#include "app/config.hpp"
#include <fstream>
#include <cstdlib>

#if defined(USE_GRPC)
#include <grpcpp/grpcpp.h>
#include "source_control.grpc.pb.h"
#include "app/errors/error_codes.h"
#endif

namespace vsm::rpc {

struct GrpcServer::Impl {
  vsm::SourceController& ctl;
  std::string addr;
  vsm::app::TlsConfig tls;
#if defined(USE_GRPC)
  class ServiceImpl final : public vsm::v1::SourceControl::Service {
  public:
    explicit ServiceImpl(vsm::SourceController& c) : ctl_(c) {}
    ::grpc::Status Attach(::grpc::ServerContext*, const vsm::v1::AttachRequest* req,
                          vsm::v1::AttachReply* resp) override {
      std::unordered_map<std::string,std::string> opts(req->options().begin(), req->options().end());
      std::string err; bool ok = ctl_.Attach(req->attach_id(), req->source_uri(), req->pipeline_id(), opts, &err);
      if (ok) { resp->set_accepted(true); return ::grpc::Status::OK; }
      // map error to gRPC status
      using vsm::errors::ErrorCode; using vsm::errors::map_message;
      ErrorCode ec = map_message(err);
      switch (ec) {
        case ErrorCode::INVALID_ARG: return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, err);
        case ErrorCode::ALREADY_EXISTS: return ::grpc::Status(::grpc::StatusCode::ALREADY_EXISTS, err);
        case ErrorCode::UNAVAILABLE: return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, err);
        default: return ::grpc::Status(::grpc::StatusCode::INTERNAL, err);
      }
    }
    ::grpc::Status Detach(::grpc::ServerContext*, const vsm::v1::DetachRequest* req,
                          vsm::v1::DetachReply* resp) override {
      std::string err; bool ok = ctl_.Detach(req->attach_id(), &err);
      if (ok) { resp->set_removed(true); return ::grpc::Status::OK; }
      using vsm::errors::ErrorCode; using vsm::errors::map_message;
      ErrorCode ec = map_message(err);
      switch (ec) {
        case ErrorCode::INVALID_ARG: return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, err);
        case ErrorCode::NOT_FOUND: return ::grpc::Status(::grpc::StatusCode::NOT_FOUND, err);
        default: return ::grpc::Status(::grpc::StatusCode::INTERNAL, err);
      }
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

    ::grpc::Status Update(::grpc::ServerContext*, const vsm::v1::UpdateRequest* req,
                          vsm::v1::UpdateReply* resp) override {
      std::unordered_map<std::string,std::string> opts(req->options().begin(), req->options().end());
      std::string err; bool ok = ctl_.Update(req->attach_id(), opts, &err);
      if (ok) { resp->set_ok(true); return ::grpc::Status::OK; }
      using vsm::errors::ErrorCode; using vsm::errors::map_message;
      ErrorCode ec = map_message(err);
      switch (ec) {
        case ErrorCode::INVALID_ARG: return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, err);
        case ErrorCode::NOT_FOUND: return ::grpc::Status(::grpc::StatusCode::NOT_FOUND, err);
        default: return ::grpc::Status(::grpc::StatusCode::INTERNAL, err);
      }
    }

    ::grpc::Status WatchState(::grpc::ServerContext* ctx, const vsm::v1::WatchStateRequest* req,
                              ::grpc::ServerWriter<vsm::v1::WatchStateReply>* writer) override {
      int wait_ms = (req && req->interval_ms()>0) ? req->interval_ms() : 25000; // treat interval as max wait
      uint64_t rev = ctl_.Revision();
      while (!ctx->IsCancelled()) {
        uint64_t new_rev = rev;
        ctl_.WaitForChange(rev, wait_ms, &new_rev);
        auto snap = ctl_.Snapshot();
        rev = snap.first;
        vsm::v1::WatchStateReply reply;
        auto now = std::chrono::time_point_cast<std::chrono::milliseconds>(std::chrono::steady_clock::now()).time_since_epoch().count();
        reply.set_ts_ms(static_cast<long long>(now));
        for (auto s : snap.second) {
          auto* it = reply.add_items();
          it->set_attach_id(s.attach_id);
          it->set_source_uri(s.source_uri);
          it->set_phase(s.phase);
          it->set_fps(s.fps);
          if (!s.profile.empty()) it->set_profile(s.profile);
          if (!s.model_id.empty()) it->set_model_id(s.model_id);
        }
        if (!writer->Write(reply)) break;
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
  explicit Impl(vsm::SourceController& c, std::string a, const vsm::app::TlsConfig& t)
    : ctl(c), addr(std::move(a)), tls(t) {}
};

GrpcServer::GrpcServer(vsm::SourceController& ctl, std::string addr)
  : impl_(std::make_unique<Impl>(ctl, std::move(addr))) {}
GrpcServer::GrpcServer(vsm::SourceController& ctl, std::string addr, const vsm::app::TlsConfig& tls)
  : impl_(std::make_unique<Impl>(ctl, std::move(addr), tls)) {}
GrpcServer::~GrpcServer() { Stop(); }

bool GrpcServer::Start() {
#if defined(USE_GRPC)
  impl_->service = new Impl::ServiceImpl(impl_->ctl);
  grpc::ServerBuilder b;
  auto read_all = [](const std::string& p){ std::ifstream f(p, std::ios::binary); return std::string((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); };
  std::shared_ptr<grpc::ServerCredentials> creds;
  // Prefer config-driven TLS. If provided, skip env path entirely.
  if (impl_->tls.enabled && (!impl_->tls.server_cert_file.empty() && !impl_->tls.server_key_file.empty())) {
    grpc::SslServerCredentialsOptions opts;
    try { if (!impl_->tls.root_cert_file.empty()) opts.pem_root_certs = read_all(impl_->tls.root_cert_file); } catch (...) {}
    try { grpc::SslServerCredentialsOptions::PemKeyCertPair pkc{ read_all(impl_->tls.server_key_file), read_all(impl_->tls.server_cert_file) }; opts.pem_key_cert_pairs.push_back(pkc); } catch (...) {}
    opts.client_certificate_request = impl_->tls.require_client_cert
      ? GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY
      : GRPC_SSL_DONT_REQUEST_CLIENT_CERTIFICATE;
    creds = grpc::SslServerCredentials(opts);
  }
  // 默认启用 TLS；如设置了环境变量 VSM_TLS_ENABLED 则允许覆盖（向后兼容）
  const char* en = std::getenv("VSM_TLS_ENABLED");
  bool enable_tls = true;
  if (en) {
    std::string v(en); for (auto& c: v) c = (char)std::tolower((unsigned char)c);
    enable_tls = (v=="1"||v=="true");
  }
  if (!creds && enable_tls) {
    // 使用绝对路径作为默认，避免工作目录差异导致解析失败；不回退到明文。
    std::string ca = std::getenv("VSM_TLS_CA")? std::getenv("VSM_TLS_CA") : std::string("D:/Projects/ai/cv/controlplane/config/certs/ca.pem");
    std::string cert = std::getenv("VSM_TLS_CERT")? std::getenv("VSM_TLS_CERT") : std::string("D:/Projects/ai/cv/controlplane/config/certs/vsm_server.crt");
    std::string key = std::getenv("VSM_TLS_KEY")? std::getenv("VSM_TLS_KEY") : std::string("D:/Projects/ai/cv/controlplane/config/certs/vsm_server.key");
    grpc::SslServerCredentialsOptions opts;
    try { if (!ca.empty()) opts.pem_root_certs = read_all(ca); } catch (...) {}
    try { grpc::SslServerCredentialsOptions::PemKeyCertPair pkc{ read_all(key), read_all(cert) }; opts.pem_key_cert_pairs.push_back(pkc); } catch (...) {}
    opts.client_certificate_request = GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY;
    creds = grpc::SslServerCredentials(opts);
  } else if (!creds) {
    creds = grpc::InsecureServerCredentials();
  }
  b.AddListeningPort(impl_->addr, creds);
  b.RegisterService(impl_->service); impl_->server = b.BuildAndStart();
  bool ok = (bool)impl_->server;
  if (ok) {
    // minimal startup log (stdout)
    std::cout << "[vsm.grpc] listening on " << impl_->addr << std::endl;
  }
  return ok;
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
