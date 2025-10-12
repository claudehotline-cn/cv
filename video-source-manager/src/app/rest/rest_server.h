#pragma once

#include <atomic>
#include <functional>
#include <string>
#include <thread>
#include <unordered_map>

namespace vsm { class SourceController; }

namespace vsm::rest {

class RestServer {
public:
  using HandlerFn = std::function<std::string(const std::string& method,
                                              const std::string& path,
                                              const std::unordered_map<std::string,std::string>& query,
                                              const std::unordered_map<std::string,std::string>& headers,
                                              const std::string& body,
                                              int* status,
                                              std::string* content_type)>;
  RestServer(int port, HandlerFn handler);
  ~RestServer();
  bool Start();
  void Stop();

private:
  void Loop();
  static std::unordered_map<std::string,std::string> parseQuery(const std::string& path);
  static std::unordered_map<std::string,std::string> parseHeaders(const std::string& raw);
  static std::string urlDecode(const std::string& in);
  void WakeAccept();

  int port_;
  HandlerFn handler_;
  std::atomic<bool> running_{false};
  std::thread th_;
  int server_fd_{-1};
};

// Helpers to构建/解析 JSON（最小实现）
std::string jsonEscape(const std::string& s);
// 解析顶层 JSON 对象的一级键值，支持 string/number/bool/null，数组/对象将原样序列化后作为字符串返回。
bool parseJsonObjectFlat(const std::string& json,
                         std::unordered_map<std::string,std::string>& out);

} // namespace vsm::rest
