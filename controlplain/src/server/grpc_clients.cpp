#include <grpcpp/grpcpp.h>
#include <memory>
#include <string>
#include <iostream>

// Generated stubs are available after proto generation; this skeleton
// only establishes channels as a reachability probe.

namespace controlplain {

std::shared_ptr<grpc::Channel> make_channel(const std::string& addr) {
  grpc::ChannelArguments args; // tune later
  return grpc::CreateCustomChannel(addr, grpc::InsecureChannelCredentials(), args);
}

bool quick_probe_va(const std::string& addr) { (void)addr; std::cout << "[controlplain] VA probe: channel created" << std::endl; return true; }
bool quick_probe_vsm(const std::string& addr) { (void)addr; std::cout << "[controlplain] VSM probe: channel created" << std::endl; return true; }

} // namespace controlplain
