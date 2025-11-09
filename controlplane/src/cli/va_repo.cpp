#include <iostream>
#include <string>
#include "controlplane/grpc_clients.hpp"

static void usage() {
  std::cerr << "Usage: va_repo --va-addr <host:port> <load|unload|poll> [model]" << std::endl;
}

int main(int argc, char** argv) {
  std::string addr; std::string cmd; std::string model;
  for (int i=1;i<argc;i++) {
    std::string a = argv[i];
    if (a == "--va-addr" && i+1<argc) { addr = argv[++i]; }
    else if (cmd.empty()) { cmd = a; }
    else if (model.empty()) { model = a; }
    else { usage(); return 2; }
  }
  if (addr.empty() || cmd.empty()) { usage(); return 2; }
  std::string err;
  bool ok = false;
  if (cmd == "load") {
    if (model.empty()) { usage(); return 2; }
    ok = controlplane::va_repo_load(addr, model, &err);
  } else if (cmd == "unload") {
    if (model.empty()) { usage(); return 2; }
    ok = controlplane::va_repo_unload(addr, model, &err);
  } else if (cmd == "poll") {
    ok = controlplane::va_repo_poll(addr, &err);
  } else {
    usage(); return 2;
  }
  if (!ok) {
    std::cerr << "repo " << cmd << " failed: " << err << std::endl; return 3;
  }
  std::cout << "repo " << cmd << " ok" << std::endl; return 0;
}

