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
#else
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <cstring>
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
  const char* msg = "OK";
  switch (code) {
    case 200: msg = "OK"; break;
    case 201: msg = "Created"; break;
    case 202: msg = "Accepted"; break;
    case 204: msg = "No Content"; break;
    case 304: msg = "Not Modified"; break;
    case 400: msg = "Bad Request"; break;
    case 401: msg = "Unauthorized"; break;
    case 403: msg = "Forbidden"; break;
    case 404: msg = "Not Found"; break;
    case 409: msg = "Conflict"; break;
    case 500: msg = "Internal Server Error"; break;
    case 502: msg = "Bad Gateway"; break;
    case 503: msg = "Service Unavailable"; break;
    case 504: msg = "Gateway Timeout"; break;
    default: msg = "OK"; break;
  }
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
  int s = static_cast<int>(reinterpret_cast<intptr_t>(opaque));
  if (s >= 0 && data && len>0) {
    ::send(s, data, len, 0);
  }
#endif
}
static void writer_close(void* opaque) {
#ifdef _WIN32
  SOCKET s = reinterpret_cast<SOCKET>(opaque);
  if (s != INVALID_SOCKET) closesocket(s);
#else
  int s = static_cast<int>(reinterpret_cast<intptr_t>(opaque));
  if (s >= 0) ::close(s);
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
      char buf[16384]; int n = recv(cli, buf, sizeof(buf), 0); if (n<=0){ closesocket(cli); continue; }
      std::string req(buf, n);
      // very small parser: first line METHOD PATH HTTP/1.1
      std::string method="GET", path="/", headers, body;
      {
        std::istringstream is(req);
        is >> method >> path; // ignore version
      }
      auto pos = req.find("\r\n\r\n");
      if (pos != std::string::npos) { headers = req.substr(0, pos); body = req.substr(pos+4); }
      // Read remaining body by Content-Length if present
      if (!headers.empty()) {
        auto hlow = headers; for (auto& c : hlow) c = (char)tolower((unsigned char)c);
        auto k = std::string("content-length:");
        auto hp = hlow.find(k);
        if (hp != std::string::npos) {
          size_t valStart = hp + k.size();
          while (valStart < headers.size() && (headers[valStart]==' '||headers[valStart]=='\t')) ++valStart;
          size_t lineEnd = headers.find("\r\n", valStart);
          std::string v = headers.substr(valStart, lineEnd==std::string::npos? std::string::npos : (lineEnd-valStart));
          long long need = 0; try { need = std::stoll(v); } catch (...) { need = 0; }
          if (need > 0 && (long long)body.size() < need) {
            long long remain = need - (long long)body.size();
            while (remain > 0) {
              int got = recv(cli, buf, (int)std::min<long long>(sizeof(buf), remain), 0);
              if (got <= 0) break;
              body.append(buf, buf+got);
              remain -= got;
            }
          }
        }
      }
      // Streaming SSE detection (minimal heuristics)
      bool isSse = (method == "GET" && (
        (path.size() >= 7 && path.rfind("/events") == path.size()-7) ||
        (path.rfind("/api/sources/watch_sse", 0) == 0) ||
        (path.rfind("/api/sources/watch", 0) == 0) ||
        (path.rfind("/api/repo/convert/events", 0) == 0)
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
  if (impl_) return false;
  auto impl = new Impl();
  impl_ = impl;
  impl->running.store(true);
  impl->handler = handler;
  int port = parse_port(listen_addr);
  impl->th = std::thread([this, impl, port, handler]() {
    int srv = ::socket(AF_INET, SOCK_STREAM, 0);
    if (srv < 0) { impl->running.store(false); return; }
    int opt = 1; ::setsockopt(srv, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
    sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_addr.s_addr = htonl(INADDR_ANY); addr.sin_port = htons(static_cast<uint16_t>(port));
    if (::bind(srv, reinterpret_cast<sockaddr*>(&addr), sizeof(addr)) < 0) { ::close(srv); impl->running.store(false); return; }
    if (::listen(srv, 8) < 0) { ::close(srv); impl->running.store(false); return; }
    while (impl->running.load()) {
      int cli = ::accept(srv, nullptr, nullptr);
      if (cli < 0) continue;
      char buf[16384]; int n = ::recv(cli, buf, sizeof(buf), 0); if (n<=0){ ::close(cli); continue; }
      std::string req(buf, n);
      std::string method="GET", path="/", headers, body;
      {
        std::istringstream is(req);
        is >> method >> path; // ignore version
      }
      auto pos = req.find("\r\n\r\n");
      if (pos != std::string::npos) { headers = req.substr(0, pos); body = req.substr(pos+4); }
      if (!headers.empty()) {
        auto hlow = headers; for (auto& c : hlow) c = (char)tolower((unsigned char)c);
        auto k = std::string("content-length:");
        auto hp = hlow.find(k);
        if (hp != std::string::npos) {
          size_t valStart = hp + k.size();
          while (valStart < headers.size() && (headers[valStart]==' '||headers[valStart]=='\t')) ++valStart;
          size_t lineEnd = headers.find("\r\n", valStart);
          std::string v = headers.substr(valStart, lineEnd==std::string::npos? std::string::npos : (lineEnd-valStart));
          long long need = 0; try { need = std::stoll(v); } catch (...) { need = 0; }
          if (need > 0 && (long long)body.size() < need) {
            long long remain = need - (long long)body.size();
            while (remain > 0) {
              int got = ::recv(cli, buf, (int)std::min<long long>(sizeof(buf), remain), 0);
              if (got <= 0) break;
              body.append(buf, buf+got);
              remain -= got;
            }
          }
        }
      }
      bool isSse = (method == "GET" && (
        (path.size() >= 7 && path.rfind("/events") == path.size()-7) ||
        (path.rfind("/api/sources/watch_sse", 0) == 0) ||
        (path.rfind("/api/sources/watch", 0) == 0) ||
        (path.rfind("/api/repo/convert/events", 0) == 0)
      ));
      if (isSse && impl->streamHandler) {
        int cli_copy = cli;
        std::string m=method, p=path, h=headers, b=body;
        std::thread([this, impl, cli_copy, m, p, h, b]() {
          StreamWriter w; w.opaque = reinterpret_cast<void*>(static_cast<intptr_t>(cli_copy)); w.send = writer_send; w.close = writer_close;
          bool accepted = false;
          try { controlplane::metrics::sse_on_open(); } catch (...) {}
          try { accepted = impl->streamHandler(m,p,h,b,w); } catch (...) { accepted = false; }
          try { controlplane::metrics::sse_on_close(); } catch (...) {}
          if (!accepted) {
            std::string resp = "HTTP/1.1 501 Not Implemented\r\nContent-Type: application/json\r\nContent-Length: 66\r\n\r\n{\"code\":\"VA_WATCH_UNAVAILABLE\",\"msg\":\"SSE requires VA Watch\"}";
            ::send(cli_copy, resp.c_str(), static_cast<int>(resp.size()), 0);
          }
          ::close(cli_copy);
        }).detach();
        continue;
      }
      HttpResponse resp = impl->handler? impl->handler(method,path,headers,body) : HttpResponse{};
      auto out = make_http_response(resp);
      ::send(cli, out.c_str(), out.size(), 0);
      ::close(cli);
    }
    ::close(srv);
  });
  return true;
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



