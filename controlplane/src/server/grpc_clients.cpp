#include <memory>
#include <string>
#include <iostream>
#include <chrono>

#include <grpcpp/grpcpp.h>

#include "analyzer_control.grpc.pb.h"
#include "source_control.grpc.pb.h"

#include "controlplane/grpc_clients.hpp"

namespace controlplane {

static std::shared_ptr<grpc::Channel> make_channel(const std::string& addr) {
  grpc::ChannelArguments args;
  args.SetMaxReceiveMessageSize(-1);
  return grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
}

bool quick_probe_va(const std::string& addr) {
  try {
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(1500));
    va::v1::QueryRuntimeRequest req;
    va::v1::QueryRuntimeReply  rep;
    auto status = stub->QueryRuntime(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = vsm::v1::SourceControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(1500));
    vsm::v1::GetHealthRequest req;
    vsm::v1::GetHealthReply  rep;
    auto status = stub->GetHealth(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(5000));
    va::v1::SubscribePipelineRequest req;
    req.set_stream_id(stream_id);
    req.set_profile(profile);
    req.set_source_uri(source_uri);
    if (!model_id.empty()) req.set_model_id(model_id);
    va::v1::SubscribePipelineReply rep;
    auto status = stub->SubscribePipeline(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(5000));
    va::v1::UnsubscribePipelineRequest req;
    req.set_stream_id(stream_id);
    req.set_profile(profile);
    va::v1::UnsubscribePipelineReply rep;
    auto status = stub->UnsubscribePipeline(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = vsm::v1::SourceControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(5000));
    vsm::v1::UpdateRequest req;
    req.set_attach_id(attach_id);
    (*req.mutable_options())["enabled"] = enabled ? "true" : "false";
    vsm::v1::UpdateReply rep;
    auto status = stub->Update(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(8000));
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
    auto status = stub->ApplyPipeline(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(8000));
    va::v1::RemovePipelineRequest req;
    req.set_pipeline_name(pipeline_name);
    va::v1::RemovePipelineReply rep;
    auto status = stub->RemovePipeline(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(15000));
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
    auto status = stub->ApplyPipelines(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(8000));
    va::v1::HotSwapModelRequest req;
    req.set_pipeline_name(pipeline_name);
    req.set_node(node);
    req.set_model_uri(model_uri);
    va::v1::HotSwapModelReply rep;
    auto status = stub->HotSwapModel(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(8000));
    va::v1::GetStatusRequest req; req.set_pipeline_name(pipeline_name);
    va::v1::GetStatusReply rep;
    auto status = stub->GetStatus(&ctx, req, &rep);
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
    auto ch = make_channel(addr);
    auto stub = va::v1::AnalyzerControl::NewStub(ch);
    grpc::ClientContext ctx;
    ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(8000 + timeout_sec*1000));
    va::v1::DrainRequest req; req.set_pipeline_name(pipeline_name); if (timeout_sec>0) req.set_timeout_sec(timeout_sec);
    va::v1::DrainReply rep;
    auto status = stub->Drain(&ctx, req, &rep);
    if (!status.ok()) { if (err) *err = status.error_message(); return false; }
    if (drained) *drained = rep.drained();
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what(); return false;
  } catch (...) {
    if (err) *err = "unknown exception"; return false;
  }
}

} // namespace controlplane


