#include <memory>
#include <string>
#include <chrono>
#include <grpcpp/grpcpp.h>
#include "lro/runner.h"
#include "lro/state_store.h"
#include "lro/status.h"
#include "lro.grpc.pb.h"

namespace lro { namespace rpcimpl {

static std::string to_status(const lro::Status s) { return lro::to_string(s); }

class LroServiceImpl final : public lro::rpc::LroService::Service {
public:
  explicit LroServiceImpl(lro::Runner* r) : runner_(r) {}

  ::grpc::Status Create(::grpc::ServerContext* /*ctx*/, const lro::rpc::CreateRequest* req, lro::rpc::CreateResponse* resp) override {
    if (!runner_) return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, "runner null");
    std::string id = runner_->create(req->spec_json(), req->idempotency_key().empty()? std::string("demo") : req->idempotency_key());
    resp->set_id(id);
    return ::grpc::Status::OK;
  }

  ::grpc::Status Get(::grpc::ServerContext* /*ctx*/, const lro::rpc::GetRequest* req, lro::rpc::GetResponse* resp) override {
    if (!runner_) return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, "runner null");
    auto op = runner_->get(req->id());
    if (!op) return ::grpc::Status(::grpc::StatusCode::NOT_FOUND, "not found");
    auto* out = resp->mutable_op();
    out->set_id(op->id);
    out->set_status(to_status(op->status.load()));
    out->set_phase(op->phase);
    out->set_reason(op->reason);
    out->set_spec_json(op->spec_json);
    out->set_result_json(op->result_json);
    try {
      auto ms = (long long)std::chrono::duration_cast<std::chrono::milliseconds>(op->created_at.time_since_epoch()).count();
      out->set_created_at_ms(ms);
    } catch (...) {}
    if (op->finished_at.time_since_epoch().count() > 0) {
      try {
        auto ms = (long long)std::chrono::duration_cast<std::chrono::milliseconds>(op->finished_at.time_since_epoch()).count();
        out->set_finished_at_ms(ms);
      } catch (...) {}
    }
    return ::grpc::Status::OK;
  }

  ::grpc::Status Cancel(::grpc::ServerContext* /*ctx*/, const lro::rpc::CancelRequest* req, lro::rpc::CancelResponse* resp) override {
    if (!runner_) return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, "runner null");
    bool ok = runner_->cancel(req->id());
    resp->set_ok(ok);
    return ::grpc::Status::OK;
  }

private:
  lro::Runner* runner_{};
};

std::unique_ptr<grpc::Server> start_grpc_server(const std::string& addr, lro::Runner* runner) {
  grpc::ServerBuilder builder;
  auto service = std::make_unique<LroServiceImpl>(runner);
  builder.AddListeningPort(addr, grpc::InsecureServerCredentials());
  builder.RegisterService(service.get());
  std::unique_ptr<grpc::Server> server(builder.BuildAndStart());
  // Service lifetime tied to server via captured unique_ptr in lambda
  (void)service.release();
  return server;
}

}} // namespace lro::rpcimpl

