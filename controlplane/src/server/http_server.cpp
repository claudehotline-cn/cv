#include "controlplane/http_server.hpp"
#include "controlplane/metrics.hpp"
#include <thread>
#include <atomic>
#include <sstream>
#include <vector>

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "ws2_32.lib")
#endif

namespace controlplane {

namespace {
struct Impl {
  std::atomic<bool> running{false};
  std::thread th;
  RouteHandler handler;
  StreamRouteHandler streamHandler;
};

static int parse_port(const std::string& listen) {
  auto pos = listen.rfind(':');
  if (pos == std::string::npos) return 8080;
  try { return std::stoi(listen.substr(pos+1)); } catch (...) { return 8080; }
}

static std::string make_http_response(const HttpResponse& r) {
  std::ostringstream os;
  int code = r.status;
  const char* msg = code==200?"OK":(code==202?"Accepted":(code==304?"Not Modified":(code==404?"Not Found":(code==501?"Not Implemented":"OK"))));
  os << "HTTP/1.1 " << code << " " << msg << "\r\n";
  os << "Content-Type: " << r.contentType << "\r\n";
  if (!r.extraHeaders.empty()) os << r.extraHeaders;
  os << "Content-Length: " << r.body.size() << "\r\n\r\n";
  os << r.body;
  return os.str();
}
}

static void writer_send(void* opaque, const char* data, size_t len) {
#ifdef _WIN32
  SOCKET s = reinterpret_cast<SOCKET>(opaque);
  if (s != INVALID_SOCKET && data && len>0) {
    send(s, data, static_cast<int>(len), 0);
  }
#else
  (void)opaque; (void)data; (void)len;
#endif
}
static void writer_close(void* opaque) {
#ifdef _WIN32
  SOCKET s = reinterpret_cast<SOCKET>(opaque);
  if (s != INVALID_SOCKET) closesocket(s);
#else
  (void)opaque;
#endif
}

bool HttpServer::start(const std::string& listen_addr, RouteHandler handler) {
#ifdef _WIN32
  if (impl_) return false;
  auto impl = new Impl();
  impl_ = impl;
  impl->running.store(true);
  impl->handler = handler;
  int port = parse_port(listen_addr);
  impl->th = std::thread([this, impl, port, handler]() {
    WSADATA wsaData; WSAStartup(MAKEWORD(2,2), &wsaData);
    SOCKET srv = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_addr.s_addr = htonl(INADDR_ANY); addr.sin_port = htons(static_cast<u_short>(port));
    bind(srv, (sockaddr*)&addr, sizeof(addr));
    ::listen(srv, 8);
    while (impl->running.load()) {
      SOCKET cli = accept(srv, nullptr, nullptr);
      if (cli == INVALID_SOCKET) continue;
      char buf[8192]; int n = recv(cli, buf, sizeof(buf)-1, 0); if (n<=0){ closesocket(cli); continue; }
      buf[n]=0;
      std::string req(buf, n);
      // very small parser: first line METHOD PATH HTTP/1.1
      std::string method="GET", path="/", headers, body;
      {
        std::istringstream is(req);
        is >> method >> path; // ignore version
      }
      auto pos = req.find("\r\n\r\n");
      if (pos != std::string::npos) { headers = req.substr(0, pos); body = req.substr(pos+4); }
      // Streaming SSE detection: subscription events (endswith /events) or sources watch endpoints
      bool isSse = (method == "GET" && (
        (path.size() >= 7 && path.rfind("/events") == path.size()-7) ||
        (path.rfind("/api/sources/watch_sse", 0) == 0) ||
        (path.rfind("/api/sources/watch", 0) == 0)
      ));
      if (isSse && impl->streamHandler) {
        SOCKET cli_copy = cli;
        std::string m=method, p=path, h=headers, b=body;
        std::thread([this, impl, cli_copy, m, p, h, b]() {
          // stream handler owns the socket
          StreamWriter w; w.opaque = reinterpret_cast<void*>(cli_copy); w.send = writer_send; w.close = writer_close;
          bool accepted = false;
          try {
            // metrics: sse connection open
            try { controlplane::metrics::sse_on_open(); } catch (...) {}
            accepted = impl->streamHandler(m,p,h,b,w);
          } catch (...) { accepted = false; }
          // metrics: sse connection close
          try { controlplane::metrics::sse_on_close(); } catch (...) {}
          if (!accepted) {
            // send 501 fallback
            std::string resp = "HTTP/1.1 501 Not Implemented\r\nContent-Type: application/json\r\nContent-Length: 66\r\n\r\n{\"code\":\"VA_WATCH_UNAVAILABLE\",\"msg\":\"SSE requires VA Watch\"}";
            send(cli_copy, resp.c_str(), static_cast<int>(resp.size()), 0);
          }
          closesocket(cli_copy);
        }).detach();
        continue;
      }
      HttpResponse resp = impl->handler? impl->handler(method,path,headers,body) : HttpResponse{};
      auto out = make_http_response(resp);
      send(cli, out.c_str(), static_cast<int>(out.size()), 0);
      closesocket(cli);
    }
    WSACleanup();
  });
  return true;
#else
  (void)listen_addr; (void)handler; return false;
#endif
}

void HttpServer::stop() {
  auto impl = static_cast<Impl*>(impl_);
  if (!impl) return;
  impl->running.store(false);
  if (impl->th.joinable()) impl->th.join();
  delete impl; impl_=nullptr;
}

bool HttpServer::start(const std::string& addr, RouteHandler handler, StreamRouteHandler streamHandler) {
  auto ok = start(addr, handler);
  if (!ok) return false;
  auto impl = static_cast<Impl*>(impl_);
  impl->streamHandler = streamHandler;
  return true;
}

} // namespace controlplane



