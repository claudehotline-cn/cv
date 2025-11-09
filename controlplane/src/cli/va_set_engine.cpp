#include <iostream>
#include <string>
#include <vector>
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"

static void usage() {
  std::cerr << "Usage: va_set_engine --va-addr <host:port> [--provider <name>] [--device <id>] [--opt k=v ...]\n";
}

int main(int argc, char** argv) {
  std::string addr; std::string provider; int device = 0; std::vector<std::string> opts;
  for (int i=1;i<argc;i++) {
    std::string a = argv[i];
    auto next = [&](){ return (i+1<argc) ? std::string(argv[++i]) : std::string(); };
    if (a == "--va-addr") addr = next();
    else if (a == "--provider") provider = next();
    else if (a == "--device") { try { device = std::stoi(next()); } catch (...) { device = 0; } }
    else if (a == "--opt" && i+1<argc) opts.push_back(next());
    else if (a == "-h" || a == "--help") { usage(); return 0; }
    else { std::cerr << "Unknown arg: " << a << "\n"; usage(); return 2; }
  }
  if (addr.empty()) { usage(); return 2; }

  grpc::ChannelArguments cargs; cargs.SetMaxReceiveMessageSize(-1);
  cargs.SetString("grpc.ssl_target_name_override", "localhost");
  cargs.SetString("grpc.default_authority", "localhost");
  auto ch = grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), cargs);
  auto stub = va::v1::AnalyzerControl::NewStub(ch);

  va::v1::SetEngineRequest req; va::v1::SetEngineReply rep; grpc::ClientContext ctx;
  if (!provider.empty()) req.set_provider(provider);
  if (device != 0) req.set_device(device);
  for (const auto& kv : opts) {
    auto p = kv.find('='); if (p == std::string::npos) continue; auto k = kv.substr(0,p); auto v = kv.substr(p+1);
    (*req.mutable_options())[k] = v;
  }
  auto st = stub->SetEngine(&ctx, req, &rep);
  if (!st.ok() || !rep.ok()) {
    std::cerr << "SetEngine failed: code=" << st.error_code() << " msg=" << (st.ok()? rep.msg() : st.error_message()) << std::endl;
    return 3;
  }
  std::cout << "provider=" << rep.provider() << " gpu=" << (rep.gpu_active()?"1":"0")
            << " io_binding=" << (rep.io_binding()?"1":"0")
            << " device_binding=" << (rep.device_binding()?"1":"0") << std::endl;
  return 0;
}

