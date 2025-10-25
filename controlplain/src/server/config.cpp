#include "controlplain/config.hpp"
#include <yaml-cpp/yaml.h>

namespace controlplain {

bool load_config(const std::string& dir, AppConfig* out, std::string* err) {
  try {
    auto path = dir + "/app.yaml";
    YAML::Node root = YAML::LoadFile(path);
    if (root["server"]) {
      auto s = root["server"]; if (s["http_listen"]) out->http_listen = s["http_listen"].as<std::string>();
    }
    if (root["va"]) {
      auto v = root["va"]; if (v["grpc_addr"]) out->va_addr = v["grpc_addr"].as<std::string>();
      if (v["timeout_ms"]) out->va_timeout_ms = v["timeout_ms"].as<int>();
      if (v["retries"]) out->va_retries = v["retries"].as<int>();
    }
    if (root["vsm"]) {
      auto v = root["vsm"]; if (v["grpc_addr"]) out->vsm_addr = v["grpc_addr"].as<std::string>();
      if (v["timeout_ms"]) out->vsm_timeout_ms = v["timeout_ms"].as<int>();
    }
    return true;
  } catch (const std::exception& ex) {
    if (err) *err = ex.what();
    return false;
  }
}

} // namespace controlplain

