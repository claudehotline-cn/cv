#pragma once
#include <string>

namespace controlplane {

struct AppConfig {
  std::string http_listen{"0.0.0.0:8080"};
  std::string va_addr{"127.0.0.1:50051"};
  std::string vsm_addr{"127.0.0.1:7070"};
  int va_timeout_ms{8000};
  int vsm_timeout_ms{8000};
  int va_retries{1};
  // restream base, e.g., rtsp://127.0.0.1:8554/
  std::string restream_rtsp_base{"rtsp://127.0.0.1:8554/"};
};

bool load_config(const std::string& dir, AppConfig* out, std::string* err);

} // namespace controlplane

