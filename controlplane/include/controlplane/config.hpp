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

struct SseOptions {
  int keepalive_ms{10000};      // send keepalive comment if no events before close
  int idle_close_ms{0};         // optional max lifetime; 0 disables
  int sources_interval_ms{1000}; // VSM WatchState request interval
};

struct DbConfig {
  // driver: "mysqlx" (X DevAPI). Empty disables DB access.
  std::string driver;            
  // X DevAPI URI (when driver=="mysqlx"), e.g., mysqlx://root:123456@127.0.0.1:33060/cv_cp?ssl-mode=disabled
  std::string mysqlx_uri;        
  // Classic (ODBC) fields (when driver=="mysql" or "odbc")
  std::string host;
  int port{0};
  std::string user;
  std::string password;
  std::string schema; // database name
  std::string odbc_driver; // optional explicit ODBC driver name
  int timeout_ms{1000};
};

struct AppConfig {
  std::string http_listen{"0.0.0.0:8080"};
  std::string va_addr{"127.0.0.1:50051"};
  std::string vsm_addr{"127.0.0.1:7070"};
  int va_timeout_ms{8000};
  int vsm_timeout_ms{8000};
  int va_retries{1};
  int vsm_retries{0};
  // restream base, e.g., rtsp://127.0.0.1:8554/
  std::string restream_rtsp_base{"rtsp://127.0.0.1:8554/"};
  SecurityConfig security{};
  TlsOptions va_tls{};
  TlsOptions vsm_tls{};
  SseOptions sse{};
  DbConfig db{};
};

bool load_config(const std::string& dir, AppConfig* out, std::string* err);

} // namespace controlplane

