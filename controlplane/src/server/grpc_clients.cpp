#include <memory>
#include <string>
#include <iostream>
#include <chrono>
#include <thread>

#include <grpcpp/grpcpp.h>
#include "controlplane/config.hpp"
#include <fstream>

#include "analyzer_control.grpc.pb.h"
#include "source_control.grpc.pb.h"

#include "controlplane/grpc_clients.hpp"
#include "controlplane/metrics.hpp"
#include "controlplane/circuit_breaker.hpp"

namespace controlplane {

static std::shared_ptr<grpc::ChannelCredentials> g_va_creds;
static std::shared_ptr<grpc::ChannelCredentials> g_vsm_creds;
static thread_local int g_last_grpc_code = -1;
static int g_va_timeout_ms = 8000;
static int g_vsm_timeout_ms = 8000;
static int g_va_retries = 0;
static int g_vsm_retries = 0;
static std::shared_ptr<grpc::Channel> make_channel(const std::string& addr, bool is_va) {
  grpc::ChannelArguments args;
  args.SetMaxReceiveMessageSize(-1);
  args.SetMaxSendMessageSize(-1);
  // Force authority/SNI to localhost to match dev certificates SAN
  args.SetString("grpc.ssl_target_name_override", "localhost");
  args.SetString("grpc.default_authority", "localhost");
  auto creds = is_va ? g_va_creds : g_vsm_creds;
  if (!creds) creds = grpc::InsecureChannelCredentials();
  return grpc::CreateCustomChannel(addr, creds, args);
}

void init_grpc_tls_from_config(const AppConfig& cfg) {
  auto build = [](const TlsOptions& opt) -> std::shared_ptr<grpc::ChannelCredentials> {
    if (!opt.enabled) return nullptr;
    grpc::SslCredentialsOptions ssl;
    try {
      if (!opt.root_cert_file.empty()) { std::ifstream f(opt.root_cert_file, std::ios::binary); ssl.pem_root_certs.assign((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); }
      if (!opt.client_cert_file.empty()) { std::ifstream f(opt.client_cert_file, std::ios::binary); ssl.pem_cert_chain.assign((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); }
      if (!opt.client_key_file.empty()) { std::ifstream f(opt.client_key_file, std::ios::binary); ssl.pem_private_key.assign((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>()); }
    } catch (...) {}
    return grpc::SslCredentials(ssl);
  };
  g_va_creds = build(cfg.va_tls);
  g_vsm_creds = build(cfg.vsm_tls);
  // capture timeouts and retry knobs
  g_va_timeout_ms = cfg.va_timeout_ms > 0 ? cfg.va_timeout_ms : 8000;
  g_vsm_timeout_ms = cfg.vsm_timeout_ms > 0 ? cfg.vsm_timeout_ms : 8000;
  g_va_retries = cfg.va_retries > 0 ? cfg.va_retries : 0;
  g_vsm_retries = cfg.vsm_retries > 0 ? cfg.vsm_retries : 0;
}

int last_grpc_status_code() { return g_last_grpc_code; }
void set_last_grpc_status_code(int code) { g_last_grpc_code = code; }

template <typename F>
static grpc::Status call_with_retry(F&& fn, bool is_va, int extra_timeout_ms = 0, const char* op = "unknown") {
  using namespace std::chrono;
  grpc::Status st;
  int retries = is_va ? g_va_retries : g_vsm_retries;
  int base_to = is_va ? g_va_timeout_ms : g_vsm_timeout_ms;
  const char* svc = is_va?"va":"vsm";
  if (!controlplane::cb::allow(svc)) {
    st = grpc::Status(grpc::StatusCode::UNAVAILABLE, "circuit open");
    g_last_grpc_code = st.error_code();
    try { controlplane::metrics::inc_backend_error(svc, op, static_cast<int>(st.error_code())); } catch (...) {}
    return st;
  }
  for (int attempt = 0; attempt <= retries; ++attempt) {
    grpc::ClientContext ctx;
    ctx.set_deadline(system_clock::now() + milliseconds(base_to + extra_timeout_ms));
    st = fn(ctx);
    g_last_grpc_code = st.error_code();
    if (st.ok()) {
      try { controlplane::cb::on_success(svc); } catch (...) {}
      break;
    }
    try { controlplane::cb::on_failure(svc); } catch (...) {}
    if (attempt < retries) std::this_thread::sleep_for(milliseconds(200 * (attempt + 1)));
  }
  if (!st.ok()) {
    try { controlplane::metrics::inc_backend_error(is_va?"va":"vsm", op, static_cast<int>(st.error_code())); } catch (...) {}
  }
  return st;
}

std::unique_ptr<va::v1::AnalyzerControl::Stub> make_va_stub(const std::string& addr) {
  auto ch = make_channel(addr, true);
  return va::v1::AnalyzerControl::NewStub(ch);
}

std::unique_ptr<vsm::v1::SourceControl::Stub> make_vsm_stub(const std::string& addr) {
  auto ch = make_channel(addr, false);
  return vsm::v1::SourceControl::NewStub(ch);
}

bool quick_probe_va(const std::string& addr) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::QueryRuntimeRequest req; va::v1::QueryRuntimeReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->QueryRuntime(&ctx, req, &rep); }, true, - (g_va_timeout_ms - 1500), "QueryRuntime" );
    if (!status.ok()) {
      std::cerr << "[controlplane] VA probe failed: code=" << status.error_code() << " msg=" << status.error_message() << std::endl;
      return false;
    }
    std::cout << "[controlplane] VA runtime: provider=" << rep.provider()
              << " gpu=" << (rep.gpu_active()?"1":"0")
              << " iob=" << (rep.io_binding()?"1":"0") << std::endl;
    return true;
  } catch (const std::exception& e) {
    std::cerr << "[controlplane] VA probe exception: " << e.what() << std::endl; return false;
  } catch (...) {
    std::cerr << "[controlplane] VA probe unknown exception" << std::endl; return false;
  }
}

bool quick_probe_vsm(const std::string& addr) {
  try {
    auto ch = make_channel(addr, false);
    auto stub = vsm::v1::SourceControl::NewStub(ch);
    vsm::v1::GetHealthRequest req; vsm::v1::GetHealthReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->GetHealth(&ctx, req, &rep); }, false, - (g_vsm_timeout_ms - 1500), "GetHealth");
    if (!status.ok()) {
      std::cerr << "[controlplane] VSM probe failed: code=" << status.error_code() << " msg=" << status.error_message() << std::endl;
      return false;
    }
    std::cout << "[controlplane] VSM health streams=" << rep.streams_size() << std::endl;
    return true;
  } catch (const std::exception& e) {
    std::cerr << "[controlplane] VSM probe exception: " << e.what() << std::endl; return false;
  } catch (...) {
    std::cerr << "[controlplane] VSM probe unknown exception" << std::endl; return false;
  }
}

bool va_subscribe(const std::string& addr,
                  const std::string& stream_id,
                  const std::string& profile,
                  const std::string& source_uri,
                  const std::string& model_id,
                  std::string* subscription_id,
                  std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::SubscribePipelineRequest req;
    req.set_stream_id(stream_id);
    req.set_profile(profile);
    req.set_source_uri(source_uri);
    if (!model_id.empty()) req.set_model_id(model_id);
    va::v1::SubscribePipelineReply rep;
    // Use configured VA timeout for Subscribe; creating pipelines may take >1.5s under load.
    // Keep retries behavior controlled by config (default 0).
    // Subscribe can be slow on cold-start (model load, pipeline init). Add generous extra timeout.
    auto status = call_with_retry(
      [&](grpc::ClientContext& ctx){ return stub->SubscribePipeline(&ctx, req, &rep); },
      true,
      /*extra_timeout_ms=*/60000,
      "SubscribePipeline"
    );
    if (!status.ok() || !rep.ok()) {
      if (err) *err = status.ok()? rep.msg() : status.error_message();
      return false;
    }
    if (subscription_id) *subscription_id = rep.subscription_id();
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_unsubscribe(const std::string& addr,
                    const std::string& stream_id,
                    const std::string& profile,
                    std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::UnsubscribePipelineRequest req;
    req.set_stream_id(stream_id);
    req.set_profile(profile);
    va::v1::UnsubscribePipelineReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->UnsubscribePipeline(&ctx, req, &rep); }, true, 0, "UnsubscribePipeline");
    if (!status.ok() || !rep.ok()) {
      if (err) *err = status.ok()? rep.msg() : status.error_message();
      return false;
    }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool vsm_set_enabled(const std::string& addr,
                     const std::string& attach_id,
                     bool enabled,
                     std::string* err) {
  try {
    auto ch = make_channel(addr, false);
    auto stub = vsm::v1::SourceControl::NewStub(ch);
    vsm::v1::UpdateRequest req;
    req.set_attach_id(attach_id);
    (*req.mutable_options())["enabled"] = enabled ? "true" : "false";
    vsm::v1::UpdateReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->Update(&ctx, req, &rep); }, false, 0, "Update");
    if (!status.ok() || !rep.ok()) {
      if (err) *err = status.ok()? rep.msg() : status.error_message();
      return false;
    }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_apply_pipeline(const std::string& addr,
                       const std::string& pipeline_name,
                       const std::string& yaml_path,
                       const std::string& graph_id,
                       const std::string& serialized,
                       const std::string& format,
                       const std::string& revision,
                       std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::ApplyPipelineRequest req;
    req.set_pipeline_name(pipeline_name);
    if (!revision.empty()) req.set_revision(revision);
    auto* spec = req.mutable_spec();
    if (!serialized.empty()) {
      spec->set_serialized(serialized);
      if (!format.empty()) spec->set_format(format);
    }
    if (!graph_id.empty()) spec->set_graph_id(graph_id);
    if (!yaml_path.empty()) spec->set_yaml_path(yaml_path);
    va::v1::ApplyPipelineReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->ApplyPipeline(&ctx, req, &rep); }, true, 0, "ApplyPipeline");
    if (!status.ok() || !rep.accepted()) {
      if (err) *err = status.ok()? rep.msg() : status.error_message();
      return false;
    }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_remove_pipeline(const std::string& addr,
                        const std::string& pipeline_name,
                        std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RemovePipelineRequest req;
    req.set_pipeline_name(pipeline_name);
    va::v1::RemovePipelineReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RemovePipeline(&ctx, req, &rep); }, true, 0, "RemovePipeline");
    if (!status.ok() || !rep.removed()) {
      if (err) *err = status.ok()? rep.msg() : status.error_message();
      return false;
    }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_apply_pipelines(const std::string& addr,
                        const std::vector<ApplyItem>& items,
                        int* accepted,
                        std::vector<std::string>* errors,
                        std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::ApplyPipelinesRequest req;
    for (const auto& it : items) {
      auto* bi = req.add_items();
      bi->set_pipeline_name(it.pipeline_name);
      if (!it.revision.empty()) bi->set_revision(it.revision);
      auto* spec = bi->mutable_spec();
      if (!it.serialized.empty()) { spec->set_serialized(it.serialized); if (!it.format.empty()) spec->set_format(it.format); }
      if (!it.graph_id.empty()) spec->set_graph_id(it.graph_id);
      if (!it.yaml_path.empty()) spec->set_yaml_path(it.yaml_path);
    }
    va::v1::ApplyPipelinesReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->ApplyPipelines(&ctx, req, &rep); }, true, 0, "ApplyPipelines");
    if (!status.ok()) { if (err) *err = status.error_message(); return false; }
    if (accepted) *accepted = rep.accepted();
    if (errors) {
      errors->clear();
      for (const auto& e : rep.errors()) errors->push_back(e);
    }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_hotswap_model(const std::string& addr,
                      const std::string& pipeline_name,
                      const std::string& node,
                      const std::string& model_uri,
                      std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::HotSwapModelRequest req;
    req.set_pipeline_name(pipeline_name);
    req.set_node(node);
    req.set_model_uri(model_uri);
    va::v1::HotSwapModelReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->HotSwapModel(&ctx, req, &rep); }, true, 0, "HotSwapModel");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_get_status(const std::string& addr,
                   const std::string& pipeline_name,
                   std::string* phase,
                   std::string* metrics_json,
                   std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::GetStatusRequest req; req.set_pipeline_name(pipeline_name);
    va::v1::GetStatusReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->GetStatus(&ctx, req, &rep); }, true, 0, "GetStatus");
    if (!status.ok()) { if (err) *err = status.error_message(); return false; }
    if (phase) *phase = rep.phase();
    if (metrics_json) *metrics_json = rep.metrics_json();
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_drain(const std::string& addr,
              const std::string& pipeline_name,
              int timeout_sec,
              bool* drained,
              std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::DrainRequest req; req.set_pipeline_name(pipeline_name); if (timeout_sec>0) req.set_timeout_sec(timeout_sec);
    va::v1::DrainReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->Drain(&ctx, req, &rep); }, true, timeout_sec*1000, "Drain");
    if (!status.ok()) { if (err) *err = status.error_message(); return false; }
    if (drained) *drained = rep.drained();
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

bool va_repo_load(const std::string& addr, const std::string& model, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoLoadRequest req; req.set_model(model);
    va::v1::RepoLoadReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoLoad(&ctx, req, &rep); }, true, 0, "RepoLoad");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; } catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_unload(const std::string& addr, const std::string& model, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoUnloadRequest req; req.set_model(model);
    va::v1::RepoUnloadReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoUnload(&ctx, req, &rep); }, true, 0, "RepoUnload");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; } catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_poll(const std::string& addr, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoPollRequest req; va::v1::RepoPollReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoPoll(&ctx, req, &rep); }, true, 0, "RepoPoll");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; } catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_list(const std::string& addr, std::vector<std::string>* models, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoListRequest req; va::v1::RepoListReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoList(&ctx, req, &rep); }, true, 0, "RepoList");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    if (models) { models->clear(); for (const auto& m : rep.models()) models->push_back(m.id()); }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; } catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_list_detail(const std::string& addr, std::vector<RepoModelInfo>* models, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoListRequest req; va::v1::RepoListReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoList(&ctx, req, &rep); }, true, 0, "RepoList");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    if (models) {
      models->clear(); models->reserve(rep.models_size());
      for (const auto& m : rep.models()) {
        RepoModelInfo info; info.id = m.id(); info.path = m.path(); info.ready = m.ready();
        info.active_version = m.active_version();
        for (const auto& v : m.versions()) info.versions.push_back(v);
        models->push_back(std::move(info));
      }
    }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; }
  catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_get_config(const std::string& addr, const std::string& model, std::string* content, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoGetConfigRequest req; req.set_model(model);
    va::v1::RepoGetConfigReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoGetConfig(&ctx, req, &rep); }, true, 0, "RepoGetConfig");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    if (content) *content = rep.content();
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; }
  catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_save_config(const std::string& addr, const std::string& model, const std::string& content, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoSaveConfigRequest req; req.set_model(model); req.set_content(content);
    va::v1::RepoSaveConfigReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoSaveConfig(&ctx, req, &rep); }, true, 0, "RepoSaveConfig");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; }
  catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_convert_upload(const std::string& addr, const std::string& model, const std::string& version, const std::string& onnx_bytes, std::string* job_id, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoConvertUploadRequest req; req.set_model(model); req.set_version(version); req.set_onnx(onnx_bytes);
    // Optional: forward TRTEXEC path if present in CP env
    const char* te = std::getenv("TRTEXEC"); if (te && *te) req.set_trtexec(te);
    va::v1::RepoConvertUploadReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoConvertUpload(&ctx, req, &rep); }, true, 0, "RepoConvertUpload");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    if (job_id) *job_id = rep.job_id();
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; }
  catch (...) { if (err) *err = "unknown exception"; return false; }
}

bool va_repo_put_file(const std::string& addr, const std::string& model, const std::string& version, const std::string& filename, const std::string& content, std::string* err) {
  try {
    auto ch = make_channel(addr, true);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    va::v1::RepoPutFileRequest req; req.set_model(model); req.set_version(version); req.set_filename(filename); req.set_content(content);
    va::v1::RepoPutFileReply rep;
    auto status = call_with_retry([&](grpc::ClientContext& ctx){ return stub->RepoPutFile(&ctx, req, &rep); }, true, 0, "RepoPutFile");
    if (!status.ok() || !rep.ok()) { if (err) *err = status.ok()? rep.msg() : status.error_message(); return false; }
    return true;
  } catch (const std::exception& e) { if (err) *err = e.what(); return false; }
  catch (...) { if (err) *err = "unknown exception"; return false; }
}

} // namespace controlplane





