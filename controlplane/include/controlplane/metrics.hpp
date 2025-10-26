#pragma once
#include <string>
#include <unordered_map>
#include <mutex>

namespace controlplane::metrics {

struct Key {
  std::string route;
  std::string method;
  int code{0};
  bool operator==(const Key& o) const noexcept { return code==o.code && route==o.route && method==o.method; }
};

struct KeyHash { size_t operator()(const Key& k) const noexcept; };

void inc_request(const std::string& route, const std::string& method, int code);
// 同步记录请求计数并附带耗时（毫秒）到直方图
void inc_request_with_ms(const std::string& route, const std::string& method, int code, double duration_ms);

std::string render_prometheus();

// SSE metrics helpers
void sse_on_open();
void sse_on_close();

// 后端 gRPC 错误统计
void inc_backend_error(const std::string& service, int grpc_code);
void inc_backend_error(const std::string& service, const std::string& method, int grpc_code);

} // namespace controlplane::metrics


