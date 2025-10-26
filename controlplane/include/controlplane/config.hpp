#pragma once
#include <string>
#include <vector>

namespace controlplane {

struct SecurityConfig {
  std::vector<std::string> cors_allowed_origins; // empty or ["*"] means allow all
  std::string bearer_token; // empty disables auth
  int rate_limit_rps{0};    // 0 disables per-route rate limit
};

struct TlsOptions {
  bool enabled{false};
  std::string root_cert_file;   // PEM file path (CA bundle)
  std::string client_cert_file; // PEM file path (optional)
  std::string client_key_file;  // PEM file path (optional)
};

struct AppConfig {
  std::string http_listen{"0.0.0.0:8080"};
  std::string va_addr{"127.0.0.1:50051"};
  std::string vsm_addr{"127.0.0.1:7070"};
  int va_timeout_ms{8000};
  int vsm_timeout_ms{8000};
  int va_retries{1};
  // restream base, e.g., rtsp://127.0.0.1:8554/
  std::string restream_rtsp_base{"rtsp://127.0.0.1:8554/"};
  SecurityConfig security{};
  TlsOptions va_tls{};
  TlsOptions vsm_tls{};
};

bool load_config(const std::string& dir, AppConfig* out, std::string* err);

} // namespace controlplane

