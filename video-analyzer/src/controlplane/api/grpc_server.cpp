#include "controlplane/api/grpc_server.hpp"
#include "controlplane/controllers/pipeline_controller.hpp"
#include "controlplane/interfaces.hpp"
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
#include <filesystem>
#include <cstdio>
#include <cstdlib>
#include <sstream>
#include <regex>
#include <cctype>
#include <unistd.h>
#include <fcntl.h>
#include <sys/wait.h>
#include <signal.h>
#include <unordered_map>

#if defined(USE_GRPC) && defined(VA_ENABLE_GRPC_SERVER)
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "whep_control.grpc.pb.h"
#include "media/whep_session.hpp"
#include "pipeline.pb.h"
#include "core/error_codes.hpp"
#if defined(USE_TRITON_INPROCESS)
#include "analyzer/triton_inproc_server_host.hpp"
#endif

namespace va { namespace control {

#if defined(USE_TRITON_INPROCESS)
namespace {
struct VaConvJob { std::mutex mu; std::vector<std::string> logs; std::string phase; std::string model; std::string version; float progress{0.f}; int pid{-1}; bool cancel{false}; };
static std::mutex g_va_conv_mu;
static std::unordered_map<std::string, std::shared_ptr<VaConvJob>> g_va_conv_jobs;

struct TrtexecShapeHint {
    std::string input_name;
    std::vector<int64_t> dims;
    int64_t max_batch{0};
};

static TrtexecShapeHint infer_shape_from_config(const va::analyzer::TritonInprocServerHost::Options& hopt,
                                                const std::string& model) {
    TrtexecShapeHint out;
    std::string content;
    bool got = false;
    // 仅支持 S3/MinIO 仓库：s3://...（与 RepoGetConfig 路径保持一致）
    if (hopt.repo.rfind("s3://", 0) == 0) {
        auto repo = hopt.repo.substr(5);
        std::string endpoint, bucket, prefix;
        if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
            auto pos = repo.find('/', repo.find("://") + 3);
            if (pos != std::string::npos) {
                endpoint = repo.substr(0, pos);
                auto rest = repo.substr(pos + 1);
                auto p2 = rest.find('/');
                if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                else { bucket = rest; prefix.clear(); }
            }
        } else {
            auto p = repo.find('/');
            if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); }
            else { bucket = repo; prefix.clear(); }
            const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
            if (ep) endpoint = ep;
        }
        if (!bucket.empty() && !endpoint.empty()) {
            if (!prefix.empty() && prefix.back() == '/') prefix.pop_back();
            std::string key = prefix.empty()? (model+"/config.pbtxt") : (prefix+"/"+model+"/config.pbtxt");
            std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
            const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
            const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
            std::ostringstream cmd;
            cmd << "curl -s --fail --connect-timeout 3 --max-time 8 ";
            cmd << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
            if (ak && sk) { cmd << "-u '" << ak << ":" << sk << "' "; }
            cmd << "'" << endpoint << "/" << bucket << "/" << key << "'";
            std::string out_buf; out_buf.reserve(32768);
            FILE* fp = popen(cmd.str().c_str(), "r");
            if (fp) {
                char buf[4096]; size_t n;
                while ((n=fread(buf,1,sizeof(buf),fp))>0) out_buf.append(buf,n);
                pclose(fp);
            }
            if (!out_buf.empty()) {
                content = std::move(out_buf);
                got = true;
            }
        }
    }

    if (!got || content.empty()) {
        return out;
    }

    // Parse max_batch_size
    {
        std::regex re_mb(R"(max_batch_size\s*:\s*([0-9]+))");
        std::smatch m;
        if (std::regex_search(content, m, re_mb)) {
            try {
                out.max_batch = std::stoll(m[1].str());
            } catch (...) {
                out.max_batch = 0;
            }
        }
    }

    // Parse first input block
    std::regex re_input(R"(input\s*\{\s*([^}]*)\})", std::regex::icase);
    std::smatch minput;
    if (!std::regex_search(content, minput, re_input)) {
        return out;
    }
    std::string block = minput[1].str();

    // name: "..."
    {
        std::regex re_name(R"(name\s*:\s*\"([^\"]+)\")");
        std::smatch m;
        if (std::regex_search(block, m, re_name)) {
            out.input_name = m[1].str();
        }
    }

    // dims: [..]
    {
        std::regex re_dims(R"(dims\s*:\s*\[([^\]]+)\])");
        std::smatch m;
        if (std::regex_search(block, m, re_dims)) {
            std::string s = m[1].str();
            std::stringstream ss(s);
            std::string tok;
            while (std::getline(ss, tok, ',')) {
                // trim
                size_t b = 0;
                while (b < tok.size() && std::isspace(static_cast<unsigned char>(tok[b]))) ++b;
                size_t e = tok.size();
                while (e > b && std::isspace(static_cast<unsigned char>(tok[e - 1]))) --e;
                if (e <= b) continue;
                try {
                    long long v = std::stoll(tok.substr(b, e - b));
                    out.dims.push_back(static_cast<int64_t>(v));
                } catch (...) {
                    // ignore invalid piece
                }
            }
        }
    }
    return out;
}
} // anonymous namespace
#endif

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
            if (!req->spec().template_id().empty()) spec.template_id = req->spec().template_id();
            for (const auto& kv : req->spec().overrides()) { spec.overrides[kv.first] = kv.second; }
            if (!req->project().empty()) spec.project = req->project();
            for (const auto& t : req->tags()) spec.tags.push_back(t);

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
            if (spec.graph_id.empty() && spec.yaml_path.empty() && spec.template_id.empty()) {
                resp->set_accepted(false);
                resp->set_msg("only graph_id/yaml_path/template_id supported in this phase");
                return mapStatus("missing graph_id/yaml_path/template_id");
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
    // M3: 批量 ApplyPipelines
    ::grpc::Status ApplyPipelines(::grpc::ServerContext*, const va::v1::ApplyPipelinesRequest* req,
                                  va::v1::ApplyPipelinesReply* resp) override {
        try {
            if (!ctl_) { resp->set_accepted(0); resp->add_errors("no controller"); return ::grpc::Status::OK; }
            int accepted = 0;
            for (const auto& item : req->items()) {
                PlainPipelineSpec spec;
                spec.name = item.pipeline_name();
                spec.revision = item.revision();
                if (!item.spec().graph_id().empty()) spec.graph_id = item.spec().graph_id();
                if (!item.spec().yaml_path().empty()) spec.yaml_path = item.spec().yaml_path();
                if (!item.spec().template_id().empty()) spec.template_id = item.spec().template_id();
                for (const auto& kv : item.spec().overrides()) spec.overrides[kv.first] = kv.second;
                spec.project = item.project();
                for (const auto& t : item.tags()) spec.tags.push_back(t);

                auto st = ctl_->Apply(spec);
                if (st.ok()) ++accepted; else resp->add_errors(st.message());
            }
            resp->set_accepted(accepted);
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            resp->add_errors(std::string("exception: ") + ex.what());
            return ::grpc::Status(::grpc::StatusCode::INTERNAL, "ApplyPipelines exception");
        } catch (...) {
            resp->add_errors("unknown exception");
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
            if (!ok) { return mapStatus(resp->msg()); }
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] UnsubscribePipeline exception: " << ex.what();
            resp->set_ok(false); resp->set_msg(std::string("exception: ") + ex.what());
            return mapStatus(resp->msg());
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Error, "control") << "[gRPC] UnsubscribePipeline unknown exception";
            resp->set_ok(false); resp->set_msg("unknown exception");
            return mapStatus(resp->msg());
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

    // P1: In-Process Triton repository controls (best-effort)
    ::grpc::Status RepoLoad(::grpc::ServerContext*, const va::v1::RepoLoadRequest* req,
                            va::v1::RepoLoadReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            hopt.model_control = "explicit"; // require explicit loading
            triton_host_ = va::analyzer::TritonInprocServerHost::instance(hopt);
            auto host = triton_host_;
            bool ok = (host && host->isReady()) ? host->loadModel(req->model()) : false;
            resp->set_ok(ok); resp->set_msg(ok?"":std::string("load failed: ")+req->model());
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) {
            resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK;
        } catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoUnload(::grpc::ServerContext*, const va::v1::RepoUnloadRequest* req,
                              va::v1::RepoUnloadReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            hopt.model_control = "explicit";
            triton_host_ = va::analyzer::TritonInprocServerHost::instance(hopt);
            auto host = triton_host_;
            bool ok = (host && host->isReady()) ? host->unloadModel(req->model()) : false;
            resp->set_ok(ok); resp->set_msg(ok?"":std::string("unload failed: ")+req->model());
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) {
            resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK;
        } catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoPoll(::grpc::ServerContext*, const va::v1::RepoPollRequest* /*req*/,
                            va::v1::RepoPollReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            // Poll requires Triton poll mode; recreate host if needed
            hopt.model_control = "poll";
            triton_host_ = va::analyzer::TritonInprocServerHost::instance(hopt);
            auto host = triton_host_;
            bool ok = (host && host->isReady()) ? host->pollRepository() : false;
            resp->set_ok(ok); resp->set_msg(ok?"":"poll failed");
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) {
            resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK;
        } catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoList(::grpc::ServerContext*, const va::v1::RepoListRequest* /*req*/,
                            va::v1::RepoListReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            // Determine currently loaded models for ready flag
            std::unordered_set<std::string> loaded;
            try {
                auto host = va::analyzer::TritonInprocServerHost::instance(hopt);
                if (host) { auto cur = host->currentLoadedModels(); loaded.insert(cur.begin(), cur.end()); }
            } catch (...) {}
            // Try local FS listing when repo is a filesystem path
            bool listed = false;
            try {
                if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                    for (const auto& entry : std::filesystem::directory_iterator(hopt.repo)) {
                        if (entry.is_directory()) {
                            auto name = entry.path().filename().string();
                            auto* m = resp->add_models(); m->set_id(name); m->set_path(entry.path().string());
                            m->set_ready(loaded.count(name) > 0);
                            // best-effort versions: numeric sub-dirs
                            try {
                                for (const auto& sub : std::filesystem::directory_iterator(entry.path())) {
                                    if (sub.is_directory()) {
                                        auto v = sub.path().filename().string();
                                        if (!v.empty() && std::all_of(v.begin(), v.end(), [](char c){ return c>='0'&&c<='9'; })) {
                                            m->add_versions(v);
                                        }
                                    }
                                }
                            } catch (...) { /* ignore */ }
                        }
                    }
                    listed = true;
                }
            } catch (...) { /* ignore and fallback */ }
            // If repo points to S3/minio, attempt ListObjectsV2 via curl with SigV4
            if (!listed && hopt.repo.rfind("s3://", 0) == 0) {
                auto repo = hopt.repo.substr(5); // strip 's3://'
                std::string endpoint, bucket, prefix;
                // Pattern 1: s3://http://host:port/bucket/prefix
                if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
                    auto pos = repo.find('/', repo.find("://") + 3);
                    if (pos != std::string::npos) {
                        endpoint = repo.substr(0, pos);
                        auto rest = repo.substr(pos + 1);
                        auto p2 = rest.find('/');
                        if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                        else { bucket = rest; prefix = std::string(); }
                    }
                } else {
                    // Pattern 2: s3://bucket/prefix (endpoint from env)
                    auto p = repo.find('/');
                    if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); }
                    else { bucket = repo; prefix.clear(); }
                    const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
                    if (ep) endpoint = ep;
                }
                if (!bucket.empty() && !endpoint.empty()) {
                    if (!prefix.empty() && prefix.back() != '/') prefix.push_back('/');
                    // Build URL for ListObjectsV2 with delimiter=/ to list immediate children
                    auto url_encode = [](const std::string& s)->std::string{
                        std::ostringstream os; for (unsigned char c : s) {
                            if ((c>='A'&&c<='Z')||(c>='a'&&c<='z')||(c>='0'&&c<='9')||c=='-'||c=='_'||c=='.'||c=='~') os<<c; else { os<<'%'<<std::uppercase<<std::hex<<std::setw(2)<<std::setfill('0')<<(int)c<<std::nouppercase<<std::dec; }
                        } return os.str(); };
                    std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
                    const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
                    const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
                    std::ostringstream cmd;
                    cmd << "curl -s --fail --connect-timeout 3 --max-time 8 ";
                    cmd << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
                    if (ak && sk) { cmd << "-u '" << ak << ":" << sk << "' "; }
                    cmd << "'" << endpoint << "/" << bucket << "?list-type=2&delimiter=%2F&prefix=" << url_encode(prefix) << "'";
                    std::string out; out.reserve(8192);
                    FILE* fp = popen(cmd.str().c_str(), "r");
                    if (fp) {
                        char buf[4096]; size_t n;
                        while ((n = fread(buf, 1, sizeof(buf), fp)) > 0) out.append(buf, n);
                        pclose(fp);
                    }
                    if (!out.empty()) {
                        // Parse XML for CommonPrefixes/Prefix elements
                        try {
                            std::regex re("<CommonPrefixes>\\s*<Prefix>([^<]+)</Prefix>\\s*</CommonPrefixes>");
                            auto begin = std::sregex_iterator(out.begin(), out.end(), re);
                            auto end = std::sregex_iterator();
                            for (auto it = begin; it != end; ++it) {
                                std::string full = (*it)[1].str();
                                if (full.rfind(prefix, 0) == 0) {
                                    std::string rest = full.substr(prefix.size());
                                    if (!rest.empty() && rest.back() == '/') rest.pop_back();
                                    if (rest.find('/') == std::string::npos && !rest.empty()) {
                                        auto* m = resp->add_models();
                                        m->set_id(rest); m->set_path(full); m->set_ready(loaded.count(rest) > 0);
                                    }
                                }
                            }
                            listed = resp->models_size() > 0;
                        } catch (...) { /* ignore parse error */ }
                    }
                }
            }
            if (!listed) {
                // Fallback: return currently known loaded models
                for (const auto& id : loaded) { auto* m = resp->add_models(); m->set_id(id); m->set_ready(true); }
            }
            resp->set_ok(true); resp->set_msg("");
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoGetConfig(::grpc::ServerContext*, const va::v1::RepoGetConfigRequest* req,
                                 va::v1::RepoGetConfigReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::string model = req->model(); if (model.empty()) { resp->set_ok(false); resp->set_msg("model required"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            std::string content;
            // FS path: <repo>/<model>/config.pbtxt
            bool got = false;
            try {
                if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                    std::filesystem::path p = std::filesystem::path(hopt.repo) / model / "config.pbtxt";
                    if (std::filesystem::exists(p)) {
                        std::ifstream ifs(p.string()); if (ifs.good()) { std::ostringstream ss; ss << ifs.rdbuf(); content = ss.str(); got = true; }
                    }
                }
            } catch (...) { /* ignore */ }
            if (!got && hopt.repo.rfind("s3://", 0) == 0) {
                // S3: GET <endpoint>/<bucket>/<prefix>/<model>/config.pbtxt with SigV4
                auto repo = hopt.repo.substr(5);
                std::string endpoint, bucket, prefix;
                if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
                    auto pos = repo.find('/', repo.find("://") + 3);
                    if (pos != std::string::npos) {
                        endpoint = repo.substr(0, pos);
                        auto rest = repo.substr(pos + 1);
                        auto p2 = rest.find('/');
                        if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                        else { bucket = rest; prefix.clear(); }
                    }
                } else {
                    auto p = repo.find('/');
                    if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); }
                    else { bucket = repo; prefix.clear(); }
                    const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
                    if (ep) endpoint = ep;
                }
                if (!bucket.empty() && !endpoint.empty()) {
                    if (!prefix.empty() && prefix.back() == '/') prefix.pop_back();
                    std::string key = prefix.empty()? (model+"/config.pbtxt") : (prefix+"/"+model+"/config.pbtxt");
                    std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
                    const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
                    const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
                    std::ostringstream cmd;
                    cmd << "curl -s --fail --connect-timeout 3 --max-time 8 ";
                    cmd << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
                    if (ak && sk) { cmd << "-u '" << ak << ":" << sk << "' "; }
                    cmd << "'" << endpoint << "/" << bucket << "/" << key << "'";
                    std::string out; out.reserve(32768);
                    FILE* fp = popen(cmd.str().c_str(), "r");
                    if (fp) { char buf[4096]; size_t n; while ((n=fread(buf,1,sizeof(buf),fp))>0) out.append(buf,n); pclose(fp); }
                    if (!out.empty()) { content = std::move(out); got = true; }
                }
            }
            resp->set_ok(got); if (!got) resp->set_msg("config not found"); else resp->set_content(content);
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoSaveConfig(::grpc::ServerContext*, const va::v1::RepoSaveConfigRequest* req,
                                  va::v1::RepoSaveConfigReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::string model = req->model(); std::string content = req->content();
            if (model.empty()) { resp->set_ok(false); resp->set_msg("model required"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            bool ok = false; std::string msg;
            // FS path write
            try {
                if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                    std::filesystem::path p = std::filesystem::path(hopt.repo) / model / "config.pbtxt";
                    std::filesystem::create_directories(p.parent_path());
                    std::ofstream ofs(p.string(), std::ios::binary | std::ios::trunc);
                    if (ofs.good()) { ofs.write(content.data(), static_cast<std::streamsize>(content.size())); ofs.close(); ok = true; }
                    else { msg = "cannot open file"; }
                }
            } catch (...) { /* ignore and try s3 */ }
            if (!ok && hopt.repo.rfind("s3://", 0) == 0) {
                // PUT to S3 via curl with SigV4 (upload temp file)
                auto repo = hopt.repo.substr(5);
                std::string endpoint, bucket, prefix;
                if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
                    auto pos = repo.find('/', repo.find("://") + 3);
                    if (pos != std::string::npos) {
                        endpoint = repo.substr(0, pos);
                        auto rest = repo.substr(pos + 1);
                        auto p2 = rest.find('/');
                        if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                        else { bucket = rest; prefix.clear(); }
                    }
                } else {
                    auto p = repo.find('/');
                    if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); }
                    else { bucket = repo; prefix.clear(); }
                    const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
                    if (ep) endpoint = ep;
                }
                if (!bucket.empty() && !endpoint.empty()) {
                    if (!prefix.empty() && prefix.back() == '/') prefix.pop_back();
                    std::string key = prefix.empty()? (model+"/config.pbtxt") : (prefix+"/"+model+"/config.pbtxt");
                    std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
                    const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
                    const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
                    // create temp file
                    char tmpname[] = "/tmp/cfgXXXXXX";
                    int fd = mkstemp(tmpname);
                    if (fd >= 0) {
                        FILE* tf = fdopen(fd, "wb"); if (tf) { fwrite(content.data(), 1, content.size(), tf); fclose(tf); }
                        std::ostringstream cmd; cmd << "curl -s --fail --connect-timeout 3 --max-time 10 ";
                        cmd << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
                        if (ak && sk) { cmd << "-u '" << ak << ":" << sk << "' "; }
                        cmd << "-T '" << tmpname << "' '" << endpoint << "/" << bucket << "/" << key << "'";
                        std::string out; FILE* fp = popen(cmd.str().c_str(), "r"); if (fp) { char b[256]; size_t n; while((n=fread(b,1,sizeof(b),fp))>0) out.append(b,n); int rc = pclose(fp); ok = (rc==0); if(!ok) msg = "s3 put failed"; }
                        unlink(tmpname);
                    } else { msg = "mkstemp failed"; }
                } else { msg = "s3 endpoint/bucket missing"; }
            }
            resp->set_ok(ok); if (!ok) resp->set_msg(msg);
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoPutFile(::grpc::ServerContext*, const va::v1::RepoPutFileRequest* req,
                                va::v1::RepoPutFileReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::string model = req->model();
            std::string version = req->version().empty()? std::string("1") : req->version();
            std::string filename = req->filename();
            const std::string& content = req->content();
            if (model.empty() || filename.empty()) { resp->set_ok(false); resp->set_msg("model/filename required"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            bool ok = false; std::string msg;
            // FS path write: <repo>/<model>/<version>/<filename>
            try {
                if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                    std::filesystem::path p = std::filesystem::path(hopt.repo) / model / version / filename;
                    std::filesystem::create_directories(p.parent_path());
                    std::ofstream ofs(p.string(), std::ios::binary | std::ios::trunc);
                    if (ofs.good()) { ofs.write(content.data(), static_cast<std::streamsize>(content.size())); ofs.close(); ok = true; }
                    else { msg = "cannot open file"; }
                }
            } catch (...) { /* ignore and try s3 */ }
            if (!ok && hopt.repo.rfind("s3://", 0) == 0) {
                // PUT to S3 via curl with SigV4 (upload temp file)
                auto repo = hopt.repo.substr(5);
                std::string endpoint, bucket, prefix;
                if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
                    auto pos = repo.find('/', repo.find("://") + 3);
                    if (pos != std::string::npos) {
                        endpoint = repo.substr(0, pos);
                        auto rest = repo.substr(pos + 1);
                        auto p2 = rest.find('/');
                        if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                        else { bucket = rest; prefix.clear(); }
                    }
                } else {
                    auto p = repo.find('/');
                    if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); }
                    else { bucket = repo; prefix.clear(); }
                    const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
                    if (ep) endpoint = ep;
                }
                if (!bucket.empty() && !endpoint.empty()) {
                    if (!prefix.empty() && prefix.back() == '/') prefix.pop_back();
                    std::string key = prefix.empty()? (model+"/"+version+"/"+filename) : (prefix+"/"+model+"/"+version+"/"+filename);
                    std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
                    const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
                    const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
                    // create temp file
                    char tmpname[] = "/tmp/repoputXXXXXX";
                    int fd = mkstemp(tmpname);
                    if (fd >= 0) {
                        FILE* tf = fdopen(fd, "wb"); if (tf) { fwrite(content.data(), 1, content.size(), tf); fclose(tf); }
                        std::ostringstream cmd; cmd << "curl -s --fail --connect-timeout 3 --max-time 30 ";
                        cmd << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
                        if (ak && sk) { cmd << "-u '" << ak << ":" << sk << "' "; }
                        cmd << "-T '" << tmpname << "' '" << endpoint << "/" << bucket << "/" << key << "'";
                        std::string out; FILE* fp = popen(cmd.str().c_str(), "r"); if (fp) { char b[256]; size_t n; while((n=fread(b,1,sizeof(b),fp))>0) out.append(b,n); int rc = pclose(fp); ok = (rc==0); if(!ok) msg = "s3 put failed"; }
                        unlink(tmpname);
                    } else { msg = "mkstemp failed"; }
                } else { msg = "s3 endpoint/bucket missing"; }
            }
            resp->set_ok(ok); if (!ok) resp->set_msg(msg);
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoConvertUpload(::grpc::ServerContext*, const va::v1::RepoConvertUploadRequest* req,
                                     va::v1::RepoConvertUploadReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::string model = req->model(); if (model.empty()) { resp->set_ok(false); resp->set_msg("model required"); return ::grpc::Status::OK; }
            std::string version = req->version().empty()? std::string("1") : req->version();
            const std::string& onnx = req->onnx(); if (onnx.empty()) { resp->set_ok(false); resp->set_msg("onnx empty"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            // Create job and dump ONNX to temp
            auto gen_id = [](){ auto now = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count(); std::ostringstream os; os << std::hex << now; return os.str(); };
            std::string job_id = gen_id();
            // use global g_va_conv_jobs
            auto append = [](std::shared_ptr<VaConvJob> j, const std::string& ln){ std::lock_guard<std::mutex> lk(j->mu); j->logs.push_back(ln); };
            // Create job record
            auto job = std::make_shared<VaConvJob>(); { std::lock_guard<std::mutex> lk(job->mu); job->phase = "created"; job->model = model; job->version = version; }
            { std::lock_guard<std::mutex> lk(g_va_conv_mu); g_va_conv_jobs[job_id] = job; }
            // Write onnx to tmp
            char onnx_tmp[] = "/tmp/va_conv_onnxXXXXXX"; int fd = mkstemp(onnx_tmp);
            if (fd < 0) { resp->set_ok(false); resp->set_msg("mkstemp failed"); return ::grpc::Status::OK; }
            FILE* tf = fdopen(fd, "wb"); if (tf) { fwrite(onnx.data(), 1, onnx.size(), tf); fclose(tf); } else { close(fd); resp->set_ok(false); resp->set_msg("fdopen failed"); return ::grpc::Status::OK; }
            std::string plan_tmp = std::string(onnx_tmp) + std::string(".plan");
            std::string trtexec;
            if (!req->trtexec().empty()) {
                trtexec = req->trtexec();
            } else if (const char* te = std::getenv("TRTEXEC"); te && *te) {
                trtexec = te;
            } else {
                const char* candidates[] = { "/usr/src/tensorrt/bin/trtexec", "/usr/local/bin/trtexec", "/usr/bin/trtexec" };
                for (const char* c : candidates) { if (access(c, X_OK) == 0) { trtexec = c; break; } }
                if (trtexec.empty()) trtexec = "trtexec";
            }
            // Infer dynamic batch/profile from config.pbtxt when possible
            TrtexecShapeHint shape_hint = infer_shape_from_config(hopt, model);
            std::string min_shapes_arg;
            std::string opt_shapes_arg;
            std::string max_shapes_arg;
            if (shape_hint.max_batch > 1 && !shape_hint.input_name.empty() && !shape_hint.dims.empty()) {
                auto build_shape = [&](int64_t b) {
                    std::ostringstream ss;
                    ss << shape_hint.input_name << ":" << b;
                    for (auto d : shape_hint.dims) {
                        ss << "x" << d;
                    }
                    return ss.str();
                };
                int64_t maxb = shape_hint.max_batch;
                int64_t optb = maxb >= 32 ? 32 : maxb;
                min_shapes_arg = std::string("--minShapes=") + build_shape(1);
                opt_shapes_arg = std::string("--optShapes=") + build_shape(optb);
                max_shapes_arg = std::string("--maxShapes=") + build_shape(maxb);
            }
            std::ostringstream cmd;
            cmd << trtexec << " --onnx='" << onnx_tmp << "' --saveEngine='" << plan_tmp << "' --fp16";
            if (!min_shapes_arg.empty()) {
                cmd << " " << min_shapes_arg << " " << opt_shapes_arg << " " << max_shapes_arg;
            }
            // Conversion thread
            std::thread([job, job_id, onnx_path=std::string(onnx_tmp), plan_tmp, cmd_str=cmd.str(), hopt, model, version, trtexec,
                         min_shapes_arg, opt_shapes_arg, max_shapes_arg]() {
                auto set_phase = [&](const char* ph, float prog){ std::lock_guard<std::mutex> lk(job->mu); job->phase = ph; if (prog >= 0.f) job->progress = prog; };
                set_phase("running", 5.f);
                // fork/exec trtexec silently, track pid for cancellation
                int pid = fork();
                if (pid == 0) {
                    // child: redirect to /dev/null and exec
                    int devnull = ::open("/dev/null", O_RDWR);
                    if (devnull >= 0) { dup2(devnull, 1); dup2(devnull, 2); }
                    std::string arg1 = std::string("--onnx=") + onnx_path;
                    std::string arg2 = std::string("--saveEngine=") + plan_tmp;
                    std::string arg_fp16 = "--fp16";
                    std::string arg_min_shapes = min_shapes_arg;
                    std::string arg_opt_shapes = opt_shapes_arg;
                    std::string arg_max_shapes = max_shapes_arg;
                    const char* argv0 = trtexec.c_str();
                    const char* argvv[16];
                    int ai = 0;
                    argvv[ai++] = argv0;
                    argvv[ai++] = arg1.c_str();
                    argvv[ai++] = arg2.c_str();
                    argvv[ai++] = arg_fp16.c_str();
                    if (!arg_min_shapes.empty()) {
                        argvv[ai++] = arg_min_shapes.c_str();
                        argvv[ai++] = arg_opt_shapes.c_str();
                        argvv[ai++] = arg_max_shapes.c_str();
                    }
                    argvv[ai] = nullptr;
                    execvp(argv0, (char* const*)argvv);
                    _exit(127);
                }
                int rc = -1;
                if (pid > 0) {
                    {
                        std::lock_guard<std::mutex> lk(job->mu); job->pid = pid;
                    }
                    // wait with cancel support
                    for (;;) {
                        int status = 0; int w = waitpid(pid, &status, WNOHANG);
                        if (w == pid) { rc = (WIFEXITED(status) ? WEXITSTATUS(status) : -1); break; }
                        bool want_cancel = false; { std::lock_guard<std::mutex> lk(job->mu); want_cancel = job->cancel; }
                        if (want_cancel) { kill(pid, SIGTERM); std::this_thread::sleep_for(std::chrono::milliseconds(200)); kill(pid, SIGKILL); rc = -1; break; }
                        std::this_thread::sleep_for(std::chrono::milliseconds(250));
                    }
                } else { rc = -1; }
                if (rc != 0) {
                    set_phase("failed", -1.f);
                    try { std::filesystem::remove(onnx_path); } catch (...) {}
                    try { std::filesystem::remove(plan_tmp); } catch (...) {}
                    return;
                }
                set_phase("uploading", 90.f);
                // Read plan and write into repo path (FS or S3) as model.plan
                std::string plan_bytes;
                try { std::ifstream ifs(plan_tmp, std::ios::binary); plan_bytes.assign(std::istreambuf_iterator<char>(ifs), std::istreambuf_iterator<char>()); } catch (...) {}
                bool ok = false; std::string msg;
                try {
                    if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                        std::filesystem::path p = std::filesystem::path(hopt.repo) / model / version / "model.plan";
                        std::filesystem::create_directories(p.parent_path());
                        std::ofstream ofs(p.string(), std::ios::binary | std::ios::trunc);
                        if (ofs.good()) { ofs.write(plan_bytes.data(), static_cast<std::streamsize>(plan_bytes.size())); ofs.close(); ok = true; }
                        else { msg = "cannot open file"; }
                    }
                } catch (...) { }
                if (!ok && hopt.repo.rfind("s3://", 0) == 0) {
                    auto repo = hopt.repo.substr(5);
                    std::string endpoint, bucket, prefix;
                    if (repo.rfind("http://", 0) == 0 || repo.rfind("https://", 0) == 0) {
                        auto pos = repo.find('/', repo.find("://") + 3);
                        if (pos != std::string::npos) {
                            endpoint = repo.substr(0, pos);
                            auto rest = repo.substr(pos + 1);
                            auto p2 = rest.find('/');
                            if (p2 != std::string::npos) { bucket = rest.substr(0, p2); prefix = rest.substr(p2 + 1); }
                            else { bucket = rest; prefix.clear(); }
                        }
                    } else {
                        auto p = repo.find('/'); if (p != std::string::npos) { bucket = repo.substr(0, p); prefix = repo.substr(p + 1); } else { bucket = repo; prefix.clear(); }
                        const char* ep = std::getenv("AWS_ENDPOINT_URL_S3"); if (!ep) ep = std::getenv("AWS_S3_ENDPOINT"); if (!ep) ep = std::getenv("AWS_ENDPOINT_URL");
                        if (ep) endpoint = ep;
                    }
                    if (!bucket.empty() && !endpoint.empty()) {
                        if (!prefix.empty() && prefix.back() == '/') prefix.pop_back();
                        std::string key = prefix.empty()? (model+"/"+version+"/model.plan") : (prefix+"/"+model+"/"+version+"/model.plan");
                        std::string region = std::getenv("AWS_REGION")? std::getenv("AWS_REGION"): (std::getenv("S3_REGION")? std::getenv("S3_REGION"): "us-east-1");
                        const char* ak = std::getenv("AWS_ACCESS_KEY_ID"); if (!ak) ak = std::getenv("S3_ACCESS_KEY_ID");
                        const char* sk = std::getenv("AWS_SECRET_ACCESS_KEY"); if (!sk) sk = std::getenv("S3_SECRET_ACCESS_KEY");
                        // write plan to tmp
                        char tmpname[] = "/tmp/va_planXXXXXX"; int fd2 = mkstemp(tmpname);
                        if (fd2 >= 0) {
                            FILE* tf2 = fdopen(fd2, "wb"); if (tf2) { fwrite(plan_bytes.data(), 1, plan_bytes.size(), tf2); fclose(tf2); }
                            std::ostringstream cmd2; cmd2 << "curl -s --fail --connect-timeout 3 --max-time 30 ";
                            cmd2 << "--aws-sigv4 \"aws:amz:" << region << ":s3\" ";
                            if (ak && sk) { cmd2 << "-u '" << ak << ":" << sk << "' "; }
                            cmd2 << "-T '" << tmpname << "' '" << endpoint << "/" << bucket << "/" << key << "'";
                            FILE* fp2 = popen(cmd2.str().c_str(), "r"); int rc2 = -1; if (fp2) { char b[128]; while (fread(b,1,sizeof(b),fp2)>0){} rc2 = pclose(fp2); }
                            unlink(tmpname); ok = (rc2==0);
                        }
                    }
                }
                set_phase(ok? "done" : "failed", ok? 100.f : -1.f);
                try { std::filesystem::remove(onnx_path); } catch (...) {}
                try { std::filesystem::remove(plan_tmp); } catch (...) {}
            }).detach();
            resp->set_ok(true); resp->set_msg(""); resp->set_job_id(job_id);
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK; }
    }

    ::grpc::Status RepoConvertStream(::grpc::ServerContext* ctx, const va::v1::RepoConvertStreamRequest* req,
                                     ::grpc::ServerWriter<va::v1::RepoConvertEvent>* writer) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            std::string job_id = req->job_id();
            // use global g_va_conv_jobs
            std::shared_ptr<VaConvJob> job;
            {
                std::lock_guard<std::mutex> lk(g_va_conv_mu);
                auto it = g_va_conv_jobs.find(job_id);
                if (it != g_va_conv_jobs.end()) job = it->second;
            }
            // If not found, just close stream
            va::v1::RepoConvertEvent ev;
            ev.set_kind("state"); ev.set_phase(job? job->phase : std::string("failed")); if (job) ev.set_progress(job->progress); writer->Write(ev);
            if (!job) return ::grpc::Status::OK;
            std::string last_phase; float last_prog = -1.f;
            for (;;) {
                if (ctx->IsCancelled()) break;
                bool finished = false; std::string phase; float prog = -1.f;
                {
                    std::lock_guard<std::mutex> lk(job->mu);
                    phase = job->phase; prog = job->progress;
                }
                if (phase != last_phase || (prog >= 0.f && prog != last_prog)) { va::v1::RepoConvertEvent e; e.set_kind("state"); e.set_phase(phase); if (prog>=0.f) e.set_progress(prog); writer->Write(e); last_phase = phase; last_prog = prog; }
                if (phase == "done" || phase == "failed") { va::v1::RepoConvertEvent e; e.set_kind("done"); e.set_phase(phase); if (prog>=0.f) e.set_progress(prog); writer->Write(e); break; }
                std::this_thread::sleep_for(std::chrono::milliseconds(250));
            }
            return ::grpc::Status::OK;
#else
            return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, "in-process disabled");
#endif
        } catch (const std::exception& ex) { return ::grpc::Status(::grpc::StatusCode::INTERNAL, ex.what()); }
        catch (...) { return ::grpc::Status(::grpc::StatusCode::INTERNAL, "unknown"); }
    }

    ::grpc::Status RepoConvertCancel(::grpc::ServerContext*, const va::v1::RepoConvertCancelRequest* req,
                                     va::v1::RepoConvertCancelReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            std::string job_id = req->job_id();
            std::shared_ptr<VaConvJob> job;
            {
                std::lock_guard<std::mutex> lk(g_va_conv_mu);
                auto it = g_va_conv_jobs.find(job_id);
                if (it != g_va_conv_jobs.end()) job = it->second;
            }
            if (!job) { resp->set_ok(false); resp->set_msg("job not found"); return ::grpc::Status::OK; }
            int pid = -1; {
                std::lock_guard<std::mutex> lk(job->mu);
                job->cancel = true; pid = job->pid;
            }
            if (pid > 0) { kill(pid, SIGTERM); }
            resp->set_ok(true); resp->set_msg(""); return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(ex.what()); return ::grpc::Status::OK; }
        catch (...) { resp->set_ok(false); resp->set_msg("unknown"); return ::grpc::Status::OK; }
    }

    // Remove model directory from repository (best-effort)
    ::grpc::Status RepoRemoveModel(::grpc::ServerContext*, const va::v1::RepoRemoveModelRequest* req,
                                   va::v1::RepoRemoveModelReply* resp) override {
        try {
#if defined(USE_TRITON_INPROCESS)
            if (!app_) { resp->set_ok(false); resp->set_msg("no application"); return ::grpc::Status::OK; }
            std::string model = req->model();
            if (model.empty()) { resp->set_ok(false); resp->set_msg("model required"); return ::grpc::Status::OK; }
            auto eng = app_->currentEngine();
            va::analyzer::TritonInprocServerHost::Options hopt;
            if (auto it = eng.options.find("triton_repo"); it != eng.options.end()) hopt.repo = it->second; else hopt.repo = "/models";
            // Try best-effort unload to avoid in-use files
            try {
                hopt.model_control = "explicit";
                triton_host_ = va::analyzer::TritonInprocServerHost::instance(hopt);
                auto host = triton_host_;
                if (host && host->isReady()) { host->unloadModel(model); }
            } catch (...) { /* ignore */ }
            // Remove from filesystem repository
            if (!hopt.repo.empty() && (hopt.repo.rfind("/", 0) == 0 || hopt.repo.find("://") == std::string::npos)) {
                try {
                    std::filesystem::path dir = std::filesystem::path(hopt.repo) / model;
                    if (std::filesystem::exists(dir)) {
                        std::error_code ec; std::filesystem::remove_all(dir, ec);
                        bool ok = !std::filesystem::exists(dir);
                        resp->set_ok(ok); resp->set_msg(ok?"":"remove failed");
                        return ::grpc::Status::OK;
                    } else {
                        resp->set_ok(true); resp->set_msg("not found");
                        return ::grpc::Status::OK;
                    }
                } catch (const std::exception& ex) {
                    resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK;
                } catch (...) {
                    resp->set_ok(false); resp->set_msg("unknown exception"); return ::grpc::Status::OK;
                }
            }
            // S3/minio repo: not implemented (requires List+DeleteObjects V2)
            resp->set_ok(false); resp->set_msg("s3 remove not implemented");
            return ::grpc::Status::OK;
#else
            resp->set_ok(false); resp->set_msg("in-process disabled"); return ::grpc::Status::OK;
#endif
        } catch (const std::exception& ex) {
            resp->set_ok(false); resp->set_msg(std::string("exception: ")+ex.what()); return ::grpc::Status::OK;
        } catch (...) { resp->set_ok(false); resp->set_msg("unknown"); return ::grpc::Status::OK; }
    }
    // Streaming phases for a subscription or (stream_id, profile) tuple.
    // Minimal implementation: poll Application pipelines and emit phase snapshots.
    ::grpc::Status Watch(::grpc::ServerContext* ctx,
                         const va::v1::WatchRequest* req,
                         ::grpc::ServerWriter<va::v1::PhaseEvent>* writer) override {
        try {
            if (!app_) {
                return ::grpc::Status(::grpc::StatusCode::UNAVAILABLE, "no application");
            }
            // Resolve target key (pipeline key) either from subscription_id or stream_id/profile
            std::string target_key;
            if (!req->subscription_id().empty()) {
                target_key = req->subscription_id();
            } else {
                auto v = app_->pipelines();
                for (const auto& p : v) {
                    if (p.stream_id == req->stream_id() && p.profile_id == req->profile()) {
                        target_key = p.key; break;
                    }
                }
            }
            if (target_key.empty()) {
                return ::grpc::Status(::grpc::StatusCode::NOT_FOUND, "subscription not found");
            }

            // Simple poll loop: emit on initial state and when running state changes; send keepalive every few seconds
            std::string last_phase;
            auto last_keep = std::chrono::steady_clock::now();
            const auto keepalive_ms = std::chrono::milliseconds(10000);
            const auto sleep_ms = std::chrono::milliseconds(300);

            while (!ctx->IsCancelled()) {
                std::string phase = "starting"; // default
                std::string reason;
                bool found = false;
                auto v = app_->pipelines();
                for (const auto& p : v) {
                    if (p.key == target_key) {
                        found = true;
                        phase = p.running ? std::string("ready") : std::string("starting_pipeline");
                        break;
                    }
                }

                // If not found at all, treat as cancelled (best-effort)
                if (!found) {
                    phase = "cancelled";
                }

                if (last_phase.empty() || phase != last_phase) {
                    va::v1::PhaseEvent ev;
                    ev.set_id(target_key);
                    ev.set_phase(phase);
                    ev.set_ts_ms(static_cast<long long>(std::chrono::duration_cast<std::chrono::milliseconds>(
                        std::chrono::system_clock::now().time_since_epoch()).count()));
                    if (!reason.empty()) ev.set_reason(reason);
                    if (!writer->Write(ev)) break;
                    last_phase = phase;
                    if (phase == "ready" || phase == "failed" || phase == "cancelled") {
                        // terminal → end stream
                        break;
                    }
                    last_keep = std::chrono::steady_clock::now();
                } else {
                    // keepalive
                    auto now = std::chrono::steady_clock::now();
                    if (now - last_keep >= keepalive_ms) {
                        va::v1::PhaseEvent ev;
                        ev.set_id(target_key);
                        ev.set_phase(last_phase);
                        ev.set_ts_ms(static_cast<long long>(std::chrono::duration_cast<std::chrono::milliseconds>(
                            std::chrono::system_clock::now().time_since_epoch()).count()));
                        if (!writer->Write(ev)) break;
                        last_keep = now;
                    }
                }

                std::this_thread::sleep_for(sleep_ms);
            }
            return ::grpc::Status::OK;
        } catch (const std::exception& ex) {
            return ::grpc::Status(::grpc::StatusCode::INTERNAL, ex.what());
        } catch (...) {
            return ::grpc::Status(::grpc::StatusCode::INTERNAL, "unknown");
        }
    }
private:
    PipelineController* ctl_ {nullptr};
    va::app::Application* app_ {nullptr};
    std::shared_ptr<va::analyzer::TritonInprocServerHost> triton_host_;
};

class WhepControlServiceImpl final : public va::whep::WhepControl::Service {
public:
    ::grpc::Status AddWhepSession(::grpc::ServerContext*, const va::whep::AddWhepSessionRequest* req,
                                  va::whep::AddWhepSessionReply* resp) override {
        try {
            std::string answer, sid; int st = va::media::WhepSessionManager::instance().createSession(req->stream_id(), req->offer_sdp(), answer, sid);
            if (st == 201) { resp->set_ok(true); resp->set_msg(""); resp->set_session_id(sid); resp->set_answer_sdp(answer); return ::grpc::Status::OK; }
            resp->set_ok(false); resp->set_msg("create failed"); return ::grpc::Status(::grpc::StatusCode::INTERNAL, resp->msg());
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(ex.what()); return ::grpc::Status(::grpc::StatusCode::INTERNAL, ex.what()); }
    }
    ::grpc::Status PatchWhepCandidate(::grpc::ServerContext*, const va::whep::PatchWhepCandidateRequest* req,
                                      va::whep::PatchWhepCandidateReply* resp) override {
        try {
            int st = va::media::WhepSessionManager::instance().patchSession(req->session_id(), req->sdp_frag());
            resp->set_ok(st==204); if (st!=204) resp->set_msg("patch failed");
            return st==204? ::grpc::Status::OK : ::grpc::Status(::grpc::StatusCode::INVALID_ARGUMENT, resp->msg());
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(ex.what()); return ::grpc::Status(::grpc::StatusCode::INTERNAL, ex.what()); }
    }
    ::grpc::Status DeleteWhepSession(::grpc::ServerContext*, const va::whep::DeleteWhepSessionRequest* req,
                                     va::whep::DeleteWhepSessionReply* resp) override {
        try {
            int st = va::media::WhepSessionManager::instance().deleteSession(req->session_id());
            resp->set_ok(st==204); if (st!=204) resp->set_msg("not found");
            return st==204? ::grpc::Status::OK : ::grpc::Status(::grpc::StatusCode::NOT_FOUND, resp->msg());
        } catch (const std::exception& ex) { resp->set_ok(false); resp->set_msg(ex.what()); return ::grpc::Status(::grpc::StatusCode::INTERNAL, ex.what()); }
    }
};

struct GrpcServerBundle { AnalyzerControlServiceImpl* svc {nullptr}; std::unique_ptr<grpc::Server> server; };

OpaquePtr StartGrpcServer(const std::string& addr, AnalyzerControlService*) {
    (void)addr; return {}; // unused overload
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl) {
    auto* svc = new AnalyzerControlServiceImpl(ctl, nullptr);
    auto* whep = new WhepControlServiceImpl();
    grpc::ServerBuilder b;
    // Allow large ONNX uploads (up to 1024MB)
    b.SetMaxReceiveMessageSize(1024 * 1024 * 1024);
    b.SetMaxSendMessageSize(1024 * 1024 * 1024);
    auto read_all = [](const std::string& p){ std::ifstream f(p, std::ios::binary); return std::string((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); };
    std::shared_ptr<grpc::ServerCredentials> creds;
    {
        const char* en = std::getenv("VA_TLS_ENABLED");
        bool enable_tls = (en && (std::string(en)=="1" || std::string(en)=="true" || std::string(en)=="TRUE"));
        if (enable_tls) {
            std::string ca = std::getenv("VA_TLS_CA")? std::getenv("VA_TLS_CA") : std::string("controlplane/config/certs/ca.pem");
            std::string cert = std::getenv("VA_TLS_CERT")? std::getenv("VA_TLS_CERT") : std::string("controlplane/config/certs/va_server.crt");
            std::string key = std::getenv("VA_TLS_KEY")? std::getenv("VA_TLS_KEY") : std::string("controlplane/config/certs/va_server.key");
            grpc::SslServerCredentialsOptions opts;
            try { if (!ca.empty()) opts.pem_root_certs = read_all(ca); } catch (...) {}
            try { grpc::SslServerCredentialsOptions::PemKeyCertPair pkc{ read_all(key), read_all(cert) }; opts.pem_key_cert_pairs.push_back(pkc); } catch (...) {}
            opts.client_certificate_request = GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY;
            creds = grpc::SslServerCredentials(opts);
        } else {
            creds = grpc::InsecureServerCredentials();
        }
    }
    b.AddListeningPort(addr, creds);
    b.RegisterService(svc);
    b.RegisterService(whep);
    std::unique_ptr<grpc::Server> server = b.BuildAndStart();
    if (!server) { delete svc; delete whep; return {}; }
    auto* bundle = new GrpcServerBundle{svc, std::move(server)};
    return OpaquePtr{bundle, [](void* p){ auto* w = reinterpret_cast<GrpcServerBundle*>(p); if (w){ if (w->server) w->server->Shutdown(); delete w->svc; /*whep owned by server*/ delete w; } }};
}

OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl, va::app::Application* app) {
    auto* svc = new AnalyzerControlServiceImpl(ctl, app);
    auto* whep = new WhepControlServiceImpl();
    grpc::ServerBuilder b;
    // Allow large ONNX uploads (up to 1024MB)
    b.SetMaxReceiveMessageSize(1024 * 1024 * 1024);
    b.SetMaxSendMessageSize(1024 * 1024 * 1024);
    auto read_all = [](const std::string& p){ std::ifstream f(p, std::ios::binary); return std::string((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); };
    std::shared_ptr<grpc::ServerCredentials> creds;
    {
        // 优先使用应用配置（默认启用 TLS）
        bool enable_tls = true;
        std::string ca, cert, key;
        bool require_client_cert = true;
        if (app) {
            const auto& tlscfg = app->appConfig().control_plane.tls;
            enable_tls = tlscfg.enabled;
            ca = tlscfg.root_cert_file;
            cert = tlscfg.server_cert_file;
            key = tlscfg.server_key_file;
            require_client_cert = tlscfg.require_client_cert;
        }
        if (enable_tls) {
            grpc::SslServerCredentialsOptions opts;
            try { if (!ca.empty()) opts.pem_root_certs = read_all(ca); } catch (...) {}
            try { grpc::SslServerCredentialsOptions::PemKeyCertPair pkc{ read_all(key), read_all(cert) }; opts.pem_key_cert_pairs.push_back(pkc); } catch (...) {}
            opts.client_certificate_request = require_client_cert
                ? GRPC_SSL_REQUEST_AND_REQUIRE_CLIENT_CERTIFICATE_AND_VERIFY
                : GRPC_SSL_DONT_REQUEST_CLIENT_CERTIFICATE;
            creds = grpc::SslServerCredentials(opts);
        } else {
            creds = grpc::InsecureServerCredentials();
        }
    }
    b.AddListeningPort(addr, creds);
    b.RegisterService(svc);
    b.RegisterService(whep);
    std::unique_ptr<grpc::Server> server = b.BuildAndStart();
    if (!server) { delete svc; delete whep; return {}; }
    auto* bundle = new GrpcServerBundle{svc, std::move(server)};
    return OpaquePtr{bundle, [](void* p){ auto* w = reinterpret_cast<GrpcServerBundle*>(p); if (w){ if (w->server) w->server->Shutdown(); delete w->svc; /*whep owned by server*/ delete w; } }};
}

#else

namespace va { namespace control {

OpaquePtr StartGrpcServer(const std::string&, AnalyzerControlService*) { return {}; }
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController*) { (void)addr; return {}; }
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController*, va::app::Application*) { (void)addr; return {}; }

#endif

} } // namespace
