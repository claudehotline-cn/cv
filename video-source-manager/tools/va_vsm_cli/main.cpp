#include <grpcpp/grpcpp.h>
#include <iostream>
#include <string>
#include <vector>
#include <unordered_map>

#include "analyzer_control.grpc.pb.h"
#include "analyzer_control.pb.h"
#include "pipeline.pb.h"
#include "source_control.grpc.pb.h"
#include "source_control.pb.h"

using grpc::Channel;
using grpc::ClientContext;
using grpc::Status;

struct Args {
    std::string va_addr = "127.0.0.1:50051";
    std::string vsm_addr = "127.0.0.1:7070";
    std::string cmd; // up|down|attach|detach|apply|subscribe|list|runtime|remove|unsubscribe
    std::unordered_map<std::string, std::string> kv;
};

static std::unordered_map<std::string,std::string> parseKV(int argc, char** argv) {
    std::unordered_map<std::string,std::string> kv;
    for (int i = 1; i < argc; ++i) {
        std::string s(argv[i]);
        auto pos = s.find('=');
        if (pos != std::string::npos) {
            kv[s.substr(0,pos)] = s.substr(pos+1);
        }
    }
    return kv;
}

static bool parseArgs(int argc, char** argv, Args& out) {
    if (argc < 2) return false;
    out.cmd = argv[1];
    for (int i = 2; i < argc; ++i) {
        std::string a(argv[i]);
        if (a.rfind("--va=",0)==0) out.va_addr = a.substr(5);
        else if (a.rfind("--vsm=",0)==0) out.vsm_addr = a.substr(6);
    }
    out.kv = parseKV(argc, argv);
    return true;
}

static void usage() {
    std::cout << "Usage:\n"
              << "  va_vsm_cli up   --va=host:50051 --vsm=host:7070 stream=camera_01 profile=det_720p uri=rtsp://... pipeline=p1 graph=analyzer_multistage_example\n"
              << "  va_vsm_cli down --va=... --vsm=... stream=camera_01 profile=det_720p attach_id=camera_01\n"
              << "  va_vsm_cli list --va=...\n"
              << "  va_vsm_cli runtime --va=...\n"
              << "  va_vsm_cli attach --vsm=... attach_id=<id> uri=<rtsp> [pipeline_id=<id>]\n"
              << "  va_vsm_cli detach --vsm=... attach_id=<id>\n"
              << "  va_vsm_cli update --vsm=... attach_id=<id> [profile=<va_profile>] [model=<model_id>]\n"
              << "  va_vsm_cli apply --va=... pipeline=<id> [graph=<graph_id>|yaml=<path>] [rev=<rev>]\n"
              << "  va_vsm_cli subscribe --va=... stream=<id> profile=<p> uri=<rtsp> [model=<id>]\n"
              << "  va_vsm_cli unsubscribe --va=... stream=<id> profile=<p>\n";
}

class VaClient {
public:
    explicit VaClient(const std::shared_ptr<Channel>& ch) : stub_(va::v1::AnalyzerControl::NewStub(ch)) {}

    bool Apply(const std::string& pipeline, const std::string& graph, const std::string& yaml, const std::string& rev) {
        va::v1::ApplyPipelineRequest req; req.set_pipeline_name(pipeline); req.set_revision(rev);
        auto* spec = req.mutable_spec();
        if (!graph.empty()) spec->set_graph_id(graph);
        if (!yaml.empty()) spec->set_yaml_path(yaml);
        va::v1::ApplyPipelineReply rep; ClientContext ctx;
        Status st = stub_->ApplyPipeline(&ctx, req, &rep);
        if (!st.ok()) {
            std::cerr << "[VA] ApplyPipeline RPC failed: " << st.error_message() << "\n"; return false;
        }
        std::cout << "[VA] apply: accepted=" << rep.accepted() << " msg=" << rep.msg() << "\n";
        return rep.accepted();
    }

    bool Subscribe(const std::string& stream, const std::string& profile, const std::string& uri, const std::string& model) {
        va::v1::SubscribePipelineRequest req; req.set_stream_id(stream); req.set_profile(profile); req.set_source_uri(uri); if(!model.empty()) req.set_model_id(model);
        va::v1::SubscribePipelineReply rep; ClientContext ctx;
        Status st = stub_->SubscribePipeline(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VA] Subscribe RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VA] subscribe: ok=" << rep.ok() << " msg=" << rep.msg() << " id=" << rep.subscription_id() << "\n";
        return rep.ok();
    }

    bool Unsubscribe(const std::string& stream, const std::string& profile) {
        va::v1::UnsubscribePipelineRequest req; req.set_stream_id(stream); req.set_profile(profile);
        va::v1::UnsubscribePipelineReply rep; ClientContext ctx;
        Status st = stub_->UnsubscribePipeline(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VA] Unsubscribe RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VA] unsubscribe: ok=" << rep.ok() << " msg=" << rep.msg() << "\n"; return rep.ok();
    }

    void List() {
        va::v1::ListPipelinesRequest req; va::v1::ListPipelinesReply rep; ClientContext ctx;
        Status st = stub_->ListPipelines(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VA] List RPC failed: " << st.error_message() << "\n"; return; }
        for (const auto& it : rep.items()) {
            std::cout << "- key=" << it.key() << " stream=" << it.stream_id() << " profile=" << it.profile() << " fps=" << it.fps() << " running=" << it.running() << "\n";
        }
    }

    void Runtime() {
        va::v1::QueryRuntimeRequest req; va::v1::QueryRuntimeReply rep; ClientContext ctx;
        Status st = stub_->QueryRuntime(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VA] Runtime RPC failed: " << st.error_message() << "\n"; return; }
        std::cout << "[VA] runtime provider=" << rep.provider() << " gpu=" << rep.gpu_active() << " io_binding=" << rep.io_binding() << " device_binding=" << rep.device_binding() << "\n";
    }

    bool Remove(const std::string& pipeline) {
        va::v1::RemovePipelineRequest req; req.set_pipeline_name(pipeline);
        va::v1::RemovePipelineReply rep; ClientContext ctx;
        Status st = stub_->RemovePipeline(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VA] Remove RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VA] remove: removed=" << rep.removed() << " msg=" << rep.msg() << "\n"; return rep.removed();
    }

private:
    std::unique_ptr<va::v1::AnalyzerControl::Stub> stub_;
};

class VsmClient {
public:
    explicit VsmClient(const std::shared_ptr<Channel>& ch) : stub_(vsm::v1::SourceControl::NewStub(ch)) {}

    bool Attach(const std::string& attach_id, const std::string& uri, const std::string& pipeline_id, const std::string& profileOpt, const std::string& modelOpt) {
        vsm::v1::AttachRequest req; req.set_attach_id(attach_id); req.set_source_uri(uri); if(!pipeline_id.empty()) req.set_pipeline_id(pipeline_id);
        if (!profileOpt.empty()) (*req.mutable_options())["profile"] = profileOpt;
        if (!modelOpt.empty()) (*req.mutable_options())["model_id"] = modelOpt;
        vsm::v1::AttachReply rep; ClientContext ctx; Status st = stub_->Attach(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VSM] Attach RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VSM] attach: accepted=" << rep.accepted() << " msg=" << rep.msg() << "\n"; return rep.accepted();
    }

    bool Detach(const std::string& attach_id) {
        vsm::v1::DetachRequest req; req.set_attach_id(attach_id);
        vsm::v1::DetachReply rep; ClientContext ctx; Status st = stub_->Detach(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VSM] Detach RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VSM] detach: removed=" << rep.removed() << " msg=" << rep.msg() << "\n"; return rep.removed();
    }

    void Health() {
        vsm::v1::GetHealthRequest req; vsm::v1::GetHealthReply rep; ClientContext ctx; Status st = stub_->GetHealth(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VSM] GetHealth RPC failed: " << st.error_message() << "\n"; return; }
        for (const auto& s : rep.streams()) {
            std::cout << "- id=" << s.attach_id() << " fps=" << s.fps() << " phase=" << s.phase() << " rtt=" << s.rtt_ms() << "ms loss=" << s.loss_pct() << "%\n";
        }
    }

    bool Update(const std::string& attach_id, const std::string& profileOpt, const std::string& modelOpt) {
        vsm::v1::UpdateRequest req; req.set_attach_id(attach_id);
        if (!profileOpt.empty()) (*req.mutable_options())["profile"] = profileOpt;
        if (!modelOpt.empty()) (*req.mutable_options())["model_id"] = modelOpt;
        vsm::v1::UpdateReply rep; ClientContext ctx; Status st = stub_->Update(&ctx, req, &rep);
        if (!st.ok()) { std::cerr << "[VSM] Update RPC failed: " << st.error_message() << "\n"; return false; }
        std::cout << "[VSM] update: ok=" << rep.ok() << " msg=" << rep.msg() << "\n";
        return rep.ok();
    }

private:
    std::unique_ptr<vsm::v1::SourceControl::Stub> stub_;
};

int main(int argc, char** argv) {
    Args a; if (!parseArgs(argc, argv, a)) { usage(); return 1; }
    auto va_ch = grpc::CreateChannel(a.va_addr, grpc::InsecureChannelCredentials());
    auto vsm_ch = grpc::CreateChannel(a.vsm_addr, grpc::InsecureChannelCredentials());
    VaClient va(va_ch); VsmClient vsm(vsm_ch);

    auto get = [&](const std::string& k)->std::string { auto it=a.kv.find(k); return it==a.kv.end()?std::string():it->second; };

    if (a.cmd == "up") {
        std::string stream = get("stream"); std::string profile = get("profile"); std::string uri = get("uri");
        std::string pipeline = get("pipeline"); std::string graph = get("graph"); std::string yaml = get("yaml"); std::string rev = get("rev");
        if (stream.empty() || profile.empty() || uri.empty() || pipeline.empty() || (graph.empty() && yaml.empty())) { usage(); return 2; }
        if (!vsm.Attach(stream, uri, pipeline, profile, /*model=*/std::string())) return 3; // attach_id == stream
        if (!va.Apply(pipeline, graph, yaml, rev)) return 4;
        if (!va.Subscribe(stream, profile, uri, /*model=*/std::string())) return 5;
        return 0;
    } else if (a.cmd == "down") {
        std::string stream = get("stream"); std::string profile = get("profile"); std::string attach = get("attach_id");
        if (stream.empty() || profile.empty() || attach.empty()) { usage(); return 2; }
        va.Unsubscribe(stream, profile);
        vsm.Detach(attach);
        return 0;
    } else if (a.cmd == "attach") {
        std::string id = get("attach_id"); std::string uri = get("uri"); std::string pipeline_id=get("pipeline_id"); std::string prof = get("profile"); std::string model = get("model");
        if (id.empty() || uri.empty()) { usage(); return 2; }
        return vsm.Attach(id, uri, pipeline_id, prof, model) ? 0 : 3;
    } else if (a.cmd == "detach") {
        std::string id = get("attach_id"); if (id.empty()) { usage(); return 2; }
        return vsm.Detach(id) ? 0 : 3;
    } else if (a.cmd == "apply") {
        std::string pipeline = get("pipeline"); std::string graph = get("graph"); std::string yaml = get("yaml"); std::string rev = get("rev");
        if (pipeline.empty() || (graph.empty() && yaml.empty())) { usage(); return 2; }
        return va.Apply(pipeline, graph, yaml, rev) ? 0 : 4;
    } else if (a.cmd == "update") {
        std::string id = get("attach_id"); std::string prof = get("profile"); std::string model = get("model");
        if (id.empty()) { usage(); return 2; }
        return vsm.Update(id, prof, model) ? 0 : 3;
    } else if (a.cmd == "subscribe") {
        std::string stream = get("stream"); std::string profile = get("profile"); std::string uri = get("uri"); std::string model=get("model");
        if (stream.empty() || profile.empty() || uri.empty()) { usage(); return 2; }
        return va.Subscribe(stream, profile, uri, model) ? 0 : 5;
    } else if (a.cmd == "unsubscribe") {
        std::string stream = get("stream"); std::string profile = get("profile"); if (stream.empty() || profile.empty()) { usage(); return 2; }
        return va.Unsubscribe(stream, profile) ? 0 : 6;
    } else if (a.cmd == "list") {
        va.List(); return 0;
    } else if (a.cmd == "runtime") {
        va.Runtime(); return 0;
    } else if (a.cmd == "remove") {
        std::string pipeline = get("pipeline"); if (pipeline.empty()) { usage(); return 2; }
        return va.Remove(pipeline) ? 0 : 7;
    }
    usage();
    return 1;
}
