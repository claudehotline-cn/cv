#include "control_plane_embedded/api/grpc_server.hpp"
#include "control_plane_embedded/controllers/pipeline_controller.hpp"
#include "control_plane_embedded/interfaces.hpp"
#include "core/logger.hpp"
#include "app/application.hpp"
#include "core/engine_manager.hpp"
#include <system_error>
#include <ratio>
#include <chrono>
#include <iterator>
#include <algorithm>
#include <string>
#include <vector>
#include <memory>

#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "pipeline.pb.h"
#include "core/error_codes.hpp"

namespace va { namespace control {

class AnalyzerControlServiceImpl final : public va::v1::AnalyzerControl::Service {
public:
    explicit AnalyzerControlServiceImpl(PipelineController* ctl, va::app::Application* app) : ctl_(ctl), app_(app) {}
    static ::grpc::Status mapStatus(const std::string& msg) {
        using va::core::errors::ErrorCode;
        auto to_code = [&](const std::string& m)->ErrorCode{
            if (m.find("missing") != std::string::npos) return ErrorCode::INVALID_ARG;
            if (m.find("not found") != std::string::npos) return ErrorCode::NOT_FOUND;
            if (m.find("already exists") != std::string::npos) return ErrorCode::ALREADY_EXISTS;
            if (m.find("unavailable") != std::string::npos) return ErrorCode::UNAVAILABLE;
            return ErrorCode::INTERNAL;
        };
        ErrorCode ec = to_code(msg);
        switch (ec) {
            case ErrorCode::INVALID_ARG: return ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, msg);
            case ErrorCode::NOT_FOUND: return ::grpc::Status(::grpc::StatusCode::NOT_FOUND, msg);
            case ErrorCode::ALREADY_EXISTS: return ::grpc::Status(::grpc::StatusCode::ALREADY_EXISTS, msg);
            case ErrorCode::UNAVAILABLE: return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, msg);
            default: return ::grpc::Status(::grpc::StatusCode::INTERNAL, msg);
        }
    }
    ::grpc::Status ApplyPipeline(::grpc::ServerContext*, const va::v1::ApplyPipelineRequest* req,
                                 va::v1::ApplyPipelineReply* resp) override {
        try {
            if (!ctl_) { resp->set_accepted(false); resp->set_msg("no controller"); return ::grpc::Status::OK; }
            PlainPipelineSpec spec;
            spec.name = req->pipeline_name();
            spec.revision = req->revision();
            if (!req->spec().graph_id().empty()) spec.graph_id = req->spec().graph_id();
            if (!req->spec().yaml_path().empty()) spec.yaml_path = req->spec().yaml_path();

            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] ApplyPipeline name='" << spec.name
                << "' rev='" << spec.revision
                << "' graph_id='" << spec.graph_id
                << "' yaml_path='" << spec.yaml_path << "'";

            if (spec.name.empty()) {
                resp->set_accepted(false);
                resp->set_msg("empty pipeline_name");
                return mapStatus("missing pipeline_name");
            }
            if (spec.graph_id.empty() && spec.yaml_path.empty()) {
                resp->set_accepted(false);
                resp->set_msg("only graph_id or yaml_path supported in this phase");
                return mapStatus("missing graph_id/yaml_path");
            }

            auto st = ctl_->Apply(spec);
            resp->set_accepted(st.ok());
            resp->set_msg(st.message());
            return st.ok()? ::grpc::Status::OK : mapStatus(st.message());
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] ApplyPipeline exception: " << ex.what();
            resp->set_accepted(false);
            resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status(::grpc::StatusCode::INTERNAL, resp->msg());
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] ApplyPipeline unknown exception";
            resp->set_accepted(false);
            resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }
    ::grpc::Status RemovePipeline(::grpc::ServerContext*, const va::v1::RemovePipelineRequest* req,
                                  va::v1::RemovePipelineReply* resp) override {
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] RemovePipeline name='" << req->pipeline_name() << "'";
            if (!ctl_) { resp->set_removed(false); resp->set_msg("no controller"); return ::grpc::Status::OK; }
            auto st = ctl_->Remove(req->pipeline_name());
            resp->set_removed(st.ok());
            resp->set_msg(st.message());
            return st.ok()? ::grpc::Status::OK : mapStatus(st.message());
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] RemovePipeline exception: " << ex.what();
            resp->set_removed(false); resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] RemovePipeline unknown exception";
            resp->set_removed(false); resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }
    ::grpc::Status HotSwapModel(::grpc::ServerContext*, const va::v1::HotSwapModelRequest* req,
                                va::v1::HotSwapModelReply* resp) override {
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] HotSwapModel name='" << req->pipeline_name()
                << "' node='" << req->node() << "' uri='" << req->model_uri() << "'";
            if (!ctl_) { resp->set_ok(false); resp->set_msg("no controller"); return ::grpc::Status::OK; }
            auto st = ctl_->HotSwapModel(req->pipeline_name(), req->node(), req->model_uri());
            resp->set_ok(st.ok()); resp->set_msg(st.message());
            return st.ok()? ::grpc::Status::OK : mapStatus(st.message());
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] HotSwapModel exception: " << ex.what();
            resp->set_ok(false); resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] HotSwapModel unknown exception";
            resp->set_ok(false); resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }
    ::grpc::Status Drain(::grpc::ServerContext*, const va::v1::DrainRequest* req,
                         va::v1::DrainReply* resp) override {
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] Drain name='" << req->pipeline_name() << "' timeout_sec=" << req->timeout_sec();
            if (!ctl_) { resp->set_drained(false); return ::grpc::Status::OK; }
            auto st = ctl_->Drain(req->pipeline_name(), req->timeout_sec());
            resp->set_drained(st.ok());
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] Drain exception: " << ex.what();
            resp->set_drained(false);
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] Drain unknown exception";
            resp->set_drained(false);
            return ::grpc::Status::OK;
        }
    }
    ::grpc::Status GetStatus(::grpc::ServerContext*, const va::v1::GetStatusRequest* req,
                             va::v1::GetStatusReply* resp) override {
        try {
            if (!ctl_) { resp->set_phase("Unknown"); resp->set_metrics_json("{}"); return ::grpc::Status::OK; }
            resp->set_phase("OK");
            resp->set_metrics_json(ctl_->GetStatus(req->pipeline_name()));
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] GetStatus exception: " << ex.what();
            resp->set_phase("Error"); resp->set_metrics_json(std::string("{\"error\":\"") + ex.what() + "\"}");
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] GetStatus unknown exception";
            resp->set_phase("Error"); resp->set_metrics_json("{\"error\":\"unknown\"}");
            return ::grpc::Status::OK;
        }
    }

    // 数据面：订阅/取消订阅
    ::grpc::Status SubscribePipeline(::grpc::ServerContext*, const va::v1::SubscribePipelineRequest* req,
                                     va::v1::SubscribePipelineReply* resp) override {
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] SubscribePipeline stream='" << req->stream_id() << "' profile='" << req->profile()
                << "' uri='" << req->source_uri() << "' model='" << req->model_id() << "'";
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::optional<std::string> model;
            if (!req->model_id().empty()) model = req->model_id();
            auto r = app_->subscribeStream(req->stream_id(), req->profile(), req->source_uri(), model);
            if (!r) { resp->set_ok(false); resp->set_msg(app_->lastError()); return mapStatus(resp->msg()); }
            resp->set_ok(true); resp->set_msg(""); resp->set_subscription_id(*r);
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] SubscribePipeline exception: " << ex.what();
            resp->set_ok(false); resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] SubscribePipeline unknown exception";
            resp->set_ok(false); resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }

    ::grpc::Status UnsubscribePipeline(::grpc::ServerContext*, const va::v1::UnsubscribePipelineRequest* req,
                                       va::v1::UnsubscribePipelineReply* resp) override {
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "control")
                << "[gRPC] UnsubscribePipeline stream='" << req->stream_id() << "' profile='" << req->profile() << "'";
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            bool ok = app_->unsubscribeStream(req->stream_id(), req->profile());
            resp->set_ok(ok); resp->set_msg(ok? std::string("") : app_->lastError());
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] UnsubscribePipeline exception: " << ex.what();
            resp->set_ok(false); resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status::OK;
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] UnsubscribePipeline unknown exception";
            resp->set_ok(false); resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }

    ::grpc::Status SetEngine(::grpc::ServerContext*, const va::v1::SetEngineRequest* req,
                             va::v1::SetEngineReply* resp) override {
        try {
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            auto current = app_->currentEngine();
            va::core::EngineDescriptor desc = current;
            if (!req->type().empty()) desc.name = req->type();
            if (!req->provider().empty()) desc.provider = req->provider();
            if (req->device() != 0) desc.device_index = req->device(); // 0 as passthrough; note: if user wants 0 explicitly, pass 0
            for (const auto& kv : req->options()) {
                desc.options[kv.first] = kv.second;
            }
            VA_LOG_C(::va::core::LogLevel::Info, "control") << "[gRPC] SetEngine provider='" << desc.provider << "' device=" << desc.device_index;
            if (!app_->setEngine(desc)) {
                resp->set_ok(false); resp->set_msg(app_->lastError());
                return mapStatus(resp->msg());
            } else {
                resp->set_ok(true); resp->set_msg("");
            }
            auto rt = app_->engineRuntimeStatus();
            resp->set_provider(desc.provider);
            resp->set_gpu_active(rt.gpu_active);
            resp->set_io_binding(rt.io_binding);
            resp->set_device_binding(rt.device_binding);
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            resp->set_ok(false); resp->set_msg(std::string("exception: ") + ex.what());
            return ::grpc::Status::OK;
        } catch (...) {
            resp->set_ok(false); resp->set_msg("unknown exception");
            return ::grpc::Status::OK;
        }
    }

    ::grpc::Status QueryRuntime(::grpc::ServerContext*, const va::v1::QueryRuntimeRequest* /*req*/,
                                va::v1::QueryRuntimeReply* resp) override {
        try {
            if (!app_) { resp->set_provider(""); resp->set_gpu_active(false); resp->set_io_binding(false); resp->set_device_binding(false); return ::grpc::Status::OK; }
            auto rt = app_->engineRuntimeStatus();
            resp->set_provider(rt.provider);
            resp->set_gpu_active(rt.gpu_active);
            resp->set_io_binding(rt.io_binding);
            resp->set_device_binding(rt.device_binding);
            return ::grpc::Status::OK;
        } catch (...) { return ::grpc::Status::OK; }
    }

    ::grpc::Status ListPipelines(::grpc::ServerContext*, const va::v1::ListPipelinesRequest* /*req*/,
                                 va::v1::ListPipelinesReply* resp) override {
        try {
            if (!app_) return ::grpc::Status::OK;
            auto v = app_->pipelines();
            for (const auto& p : v) {
                auto* item = resp->add_items();
                item->set_key(p.key);
                item->set_stream_id(p.stream_id);
                item->set_profile(p.profile_id);
                item->set_source_uri(p.source_uri);
                item->set_model_id(p.model_id);
                item->set_task(p.task);
                item->set_running(p.running);
                item->set_fps(p.metrics.fps);
                item->set_processed_frames(p.metrics.processed_frames);
                item->set_dropped_frames(p.metrics.dropped_frames);
                item->set_transport_packets(p.transport_stats.packets);
                item->set_transport_bytes(p.transport_stats.bytes);
                item->set_decoder_label(p.decoder_label);
            }
            return ::grpc::Status::OK;
        } catch (...) {
            return ::grpc::Status::OK;
        }
    }
private:
    PipelineController* ctl_ {nullptr};
    va::app::Application* app_ {nullptr};
};

struct GrpcServerBundle { AnalyzerControlServiceImpl* svc {nullptr}; std::unique_ptr<grpc::Server> server; };

OpaquePtr StartGrpcServer(const std::string& addr, AnalyzerControlService*) {
    (void)addr; return {}; // unused overload
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl) {
    auto* svc = new AnalyzerControlServiceImpl(ctl, nullptr);
    grpc::ServerBuilder b;
    b.AddListeningPort(addr, grpc::InsecureServerCredentials());
    b.RegisterService(svc);
    std::unique_ptr<grpc::Server> server = b.BuildAndStart();
    if (!server) { delete svc; return {}; }
    auto* bundle = new GrpcServerBundle{svc, std::move(server)};
    return OpaquePtr{bundle, [](void* p){ auto* w = reinterpret_cast<GrpcServerBundle*>(p); if (w){ if (w->server) w->server->Shutdown(); delete w->svc; delete w; } }};
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl, va::app::Application* app) {
    auto* svc = new AnalyzerControlServiceImpl(ctl, app);
    grpc::ServerBuilder b;
    b.AddListeningPort(addr, grpc::InsecureServerCredentials());
    b.RegisterService(svc);
    std::unique_ptr<grpc::Server> server = b.BuildAndStart();
    if (!server) { delete svc; return {}; }
    auto* bundle = new GrpcServerBundle{svc, std::move(server)};
    return OpaquePtr{bundle, [](void* p){ auto* w = reinterpret_cast<GrpcServerBundle*>(p); if (w){ if (w->server) w->server->Shutdown(); delete w->svc; delete w; } }};
}

#else

namespace va { namespace control {

OpaquePtr StartGrpcServer(const std::string&, AnalyzerControlService*) { return {}; }
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController*) { (void)addr; return {}; }
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController*, va::app::Application*) { (void)addr; return {}; }

#endif

} } // namespace
