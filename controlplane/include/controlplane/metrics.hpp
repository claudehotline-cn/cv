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

std::string render_prometheus();

// SSE metrics helpers
void sse_on_open();
void sse_on_close();

} // namespace controlplane::metrics

