#include "controlplane/config.hpp"
#include <yaml-cpp/yaml.h>

namespace controlplane {

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
      if (v["tls"]) {
        auto t = v["tls"]; if (t["enabled"]) out->va_tls.enabled = t["enabled"].as<bool>(false);
        if (t["root_cert_file"]) out->va_tls.root_cert_file = t["root_cert_file"].as<std::string>("");
        if (t["client_cert_file"]) out->va_tls.client_cert_file = t["client_cert_file"].as<std::string>("");
        if (t["client_key_file"]) out->va_tls.client_key_file = t["client_key_file"].as<std::string>("");
      }
    }
    if (root["vsm"]) {
      auto v = root["vsm"]; if (v["grpc_addr"]) out->vsm_addr = v["grpc_addr"].as<std::string>();
      if (v["timeout_ms"]) out->vsm_timeout_ms = v["timeout_ms"].as<int>();
      if (v["tls"]) {
        auto t = v["tls"]; if (t["enabled"]) out->vsm_tls.enabled = t["enabled"].as<bool>(false);
        if (t["root_cert_file"]) out->vsm_tls.root_cert_file = t["root_cert_file"].as<std::string>("");
        if (t["client_cert_file"]) out->vsm_tls.client_cert_file = t["client_cert_file"].as<std::string>("");
        if (t["client_key_file"]) out->vsm_tls.client_key_file = t["client_key_file"].as<std::string>("");
      }
    }
    if (root["restream"]) {
      auto r = root["restream"]; if (r["rtsp_base"]) out->restream_rtsp_base = r["rtsp_base"].as<std::string>();
    }
    if (root["security"]) {
      auto s = root["security"];
      if (s["cors"]) {
        auto c = s["cors"];
        if (c["allowed_origins"]) {
          out->security.cors_allowed_origins.clear();
          for (auto it : c["allowed_origins"]) {
            try { out->security.cors_allowed_origins.push_back(it.as<std::string>()); } catch (...) {}
          }
        }
      }
      if (s["auth"]) {
        auto a = s["auth"]; if (a["bearer_token"]) out->security.bearer_token = a["bearer_token"].as<std::string>("");
      }
      if (s["rate_limit"]) {
        auto rl = s["rate_limit"]; if (rl["rps"]) out->security.rate_limit_rps = rl["rps"].as<int>(0);
      }
    }
    if (out->security.cors_allowed_origins.empty()) {
      out->security.cors_allowed_origins.push_back("*");
    }
    return true;
  } catch (const std::exception& ex) {
    if (err) *err = ex.what();
    return false;
  }
}

} // namespace controlplane

