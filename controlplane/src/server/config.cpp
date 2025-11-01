#include "controlplane/config.hpp"
#include <yaml-cpp/yaml.h>

namespace controlplane {

static inline std::string make_abs(const std::string& dir, const std::string& p) {
  if (p.empty()) return p;
  if (p.size() > 1 && (p[1] == ':' || p[0] == '/' || p[0] == '\\')) return p;
  return dir + "/" + p;
}

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
        if (t["root_cert_file"]) out->va_tls.root_cert_file = make_abs(dir, t["root_cert_file"].as<std::string>(""));
        if (t["client_cert_file"]) out->va_tls.client_cert_file = make_abs(dir, t["client_cert_file"].as<std::string>(""));
        if (t["client_key_file"]) out->va_tls.client_key_file = make_abs(dir, t["client_key_file"].as<std::string>(""));
      }
    }
    if (root["vsm"]) {
      auto v = root["vsm"]; if (v["grpc_addr"]) out->vsm_addr = v["grpc_addr"].as<std::string>();
      if (v["timeout_ms"]) out->vsm_timeout_ms = v["timeout_ms"].as<int>();
      if (v["retries"]) out->vsm_retries = v["retries"].as<int>(0);
      if (v["tls"]) {
        auto t = v["tls"]; if (t["enabled"]) out->vsm_tls.enabled = t["enabled"].as<bool>(false);
        if (t["root_cert_file"]) out->vsm_tls.root_cert_file = make_abs(dir, t["root_cert_file"].as<std::string>(""));
        if (t["client_cert_file"]) out->vsm_tls.client_cert_file = make_abs(dir, t["client_cert_file"].as<std::string>(""));
        if (t["client_key_file"]) out->vsm_tls.client_key_file = make_abs(dir, t["client_key_file"].as<std::string>(""));
      }
    }
    if (root["restream"]) {
      auto r = root["restream"]; if (r["rtsp_base"]) out->restream_rtsp_base = r["rtsp_base"].as<std::string>();
    }
    if (root["sfu"]) {
      auto sfu = root["sfu"];
      if (sfu["whep_base"]) out->sfu_whep_base = sfu["whep_base"].as<std::string>(out->sfu_whep_base);
      if (sfu["default_variant"]) out->sfu_whep_default_variant = sfu["default_variant"].as<std::string>(out->sfu_whep_default_variant);
      if (sfu["pause_policy"]) out->sfu_pause_policy = sfu["pause_policy"].as<std::string>(out->sfu_pause_policy);
    }
    if (root["sse"]) {
      auto s = root["sse"];
      if (s["keepalive_ms"]) out->sse.keepalive_ms = s["keepalive_ms"].as<int>(out->sse.keepalive_ms);
      if (s["idle_close_ms"]) out->sse.idle_close_ms = s["idle_close_ms"].as<int>(out->sse.idle_close_ms);
      if (s["sources"]) {
        auto so = s["sources"]; if (so["interval_ms"]) out->sse.sources_interval_ms = so["interval_ms"].as<int>(out->sse.sources_interval_ms);
      }
    }
    if (root["db"]) {
      auto d = root["db"];
      if (d["driver"]) out->db.driver = d["driver"].as<std::string>(out->db.driver);
      if (d["mysqlx_uri"]) out->db.mysqlx_uri = d["mysqlx_uri"].as<std::string>(out->db.mysqlx_uri);
      if (d["host"]) out->db.host = d["host"].as<std::string>(out->db.host);
      if (d["port"]) out->db.port = d["port"].as<int>(out->db.port);
      if (d["user"]) out->db.user = d["user"].as<std::string>(out->db.user);
      if (d["password"]) out->db.password = d["password"].as<std::string>(out->db.password);
      if (d["schema"]) out->db.schema = d["schema"].as<std::string>(out->db.schema);
      if (d["odbc_driver"]) out->db.odbc_driver = d["odbc_driver"].as<std::string>(out->db.odbc_driver);
      if (d["timeout_ms"]) out->db.timeout_ms = d["timeout_ms"].as<int>(out->db.timeout_ms);
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

