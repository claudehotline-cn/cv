#pragma once
#include <functional>
#include <string>

namespace controlplane {

struct HttpResponse {
  int status{200};
  std::string contentType{"application/json"};
  std::string body{"{}"};
  std::string extraHeaders; // raw lines ending with \r\n
};

using RouteHandler = std::function<HttpResponse(const std::string& method,
                                                const std::string& path,
                                                const std::string& headers,
                                                const std::string& body)>;

struct StreamWriter {
  void* opaque{nullptr};
  void (*send)(void* opaque, const char* data, size_t len){nullptr};
  void (*close)(void* opaque){nullptr};
};

using StreamRouteHandler = std::function<bool(const std::string& method,
                                              const std::string& path,
                                              const std::string& headers,
                                              const std::string& body,
                                              StreamWriter writer)>;

class HttpServer {
public:
  // listen is host:port, e.g., 0.0.0.0:8080; Windows-only minimal impl
  bool start(const std::string& addr, RouteHandler handler);
  bool start(const std::string& addr, RouteHandler handler, StreamRouteHandler streamHandler);
  void stop();
private:
  void* impl_{nullptr};
};

} // namespace controlplane

