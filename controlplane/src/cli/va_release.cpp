#include <iostream>
#include <string>
#include <unordered_map>
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"

static void print_usage() {
  std::cerr << "Usage: va_release --va-addr <host:port> --pipeline <name> --node <node> [--model-uri <path>] [--triton-model <name>] [--triton-version <ver>]" << std::endl;
}

struct Args {
  std::string va_addr;
  std::string pipeline;
  std::string node;
  std::string model_uri;       // for ORT/TRT
  std::string triton_model;    // for Triton (in-process/grpc)
  std::string triton_version;  // optional
};

static bool parse_args(int argc, char** argv, Args* out) {
  Args a;
  for (int i=1;i<argc;i++) {
    std::string k = argv[i];
    auto next = [&](){ return (i+1<argc) ? std::string(argv[++i]) : std::string(); };
    if (k == "--va-addr") a.va_addr = next();
    else if (k == "--pipeline") a.pipeline = next();
    else if (k == "--node") a.node = next();
    else if (k == "--model-uri") a.model_uri = next();
    else if (k == "--triton-model") a.triton_model = next();
    else if (k == "--triton-version") a.triton_version = next();
    else { std::cerr << "Unknown arg: " << k << std::endl; return false; }
  }
  if (a.va_addr.empty() || a.pipeline.empty() || a.node.empty()) return false;
  *out = std::move(a); return true;
}

int main(int argc, char** argv) {
  Args args; if (!parse_args(argc, argv, &args)) { print_usage(); return 2; }

  grpc::ChannelArguments cargs; cargs.SetMaxReceiveMessageSize(-1);
  cargs.SetString("grpc.ssl_target_name_override", "localhost");
  cargs.SetString("grpc.default_authority", "localhost");
  auto ch = grpc::CreateCustomChannel(args.va_addr, grpc::InsecureChannelCredentials(), cargs);
  auto stub = va::v1::AnalyzerControl::NewStub(ch);

  // Optional: SetEngine to override Triton model/version before swap
  if (!args.triton_model.empty() || !args.triton_version.empty()) {
    va::v1::SetEngineRequest sreq; va::v1::SetEngineReply srep;
    // provider left empty to preserve current; only options override
    if (!args.triton_model.empty()) (*sreq.mutable_options())["triton_model"] = args.triton_model;
    if (!args.triton_version.empty()) (*sreq.mutable_options())["triton_model_version"] = args.triton_version;
    grpc::ClientContext sctx;
    auto sst = stub->SetEngine(&sctx, sreq, &srep);
    if (!sst.ok() || !srep.ok()) {
      std::cerr << "SetEngine failed: code=" << sst.error_code() << " msg=" << (sst.ok()? srep.msg() : sst.error_message()) << std::endl;
      return 3;
    }
    std::cout << "SetEngine ok: provider=" << srep.provider() << " gpu=" << (srep.gpu_active()?"1":"0") << std::endl;
  }

  // HotSwapModel to trigger session reopen and warmup on first run
  {
    va::v1::HotSwapModelRequest req; va::v1::HotSwapModelReply rep; grpc::ClientContext ctx;
    req.set_pipeline_name(args.pipeline);
    req.set_node(args.node);
    if (!args.model_uri.empty()) req.set_model_uri(args.model_uri);
    else req.set_model_uri("__triton__"); // placeholder for Triton path; ignored by in-process session
    auto st = stub->HotSwapModel(&ctx, req, &rep);
    if (!st.ok() || !rep.ok()) {
      std::cerr << "HotSwapModel failed: code=" << st.error_code() << " msg=" << (st.ok()? rep.msg() : st.error_message()) << std::endl;
      return 4;
    }
  }

  std::cout << "Release completed: pipeline='" << args.pipeline << "' node='" << args.node << "'" << std::endl;
  return 0;
}

