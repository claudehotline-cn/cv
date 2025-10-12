#include "app/rest/rest_server.h"
#include <algorithm>
#include <cctype>
#include <cstring>
#include <sstream>
#include <iostream>

#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#else
#  include <sys/types.h>
#  include <sys/socket.h>
#  include <netinet/in.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#endif

namespace vsm::rest {

static inline void closesock(int fd) {
#ifdef _WIN32
  ::closesocket(fd);
#else
  ::close(fd);
#endif
}

RestServer::RestServer(int port, HandlerFn handler)
  : port_(port), handler_(std::move(handler)) {}

RestServer::~RestServer() { Stop(); }

bool RestServer::Start() {
  if (running_) return true;
  running_ = true;
  th_ = std::thread(&RestServer::Loop, this);
  return true;
}

void RestServer::Stop() {
  if (!running_) return;
  running_ = false;
  try { WakeAccept(); } catch (...) {}
  if (th_.joinable()) th_.join();
}

void RestServer::Loop() {
#ifdef _WIN32
  WSADATA wsaData; WSAStartup(MAKEWORD(2,2), &wsaData);
#endif
  server_fd_ = static_cast<int>(::socket(AF_INET, SOCK_STREAM, 0));
  if (server_fd_ < 0) { std::cerr << "[rest] socket failed" << std::endl; running_ = false; return; }
  int opt = 1;
#ifdef _WIN32
  ::setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
  ::setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif
  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_addr.s_addr = INADDR_ANY; addr.sin_port = htons((uint16_t)port_);
  if (::bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) { std::cerr << "[rest] bind failed :" << port_ << std::endl; closesock(server_fd_); server_fd_=-1; running_=false; return; }
  if (::listen(server_fd_, 32) < 0) { std::cerr << "[rest] listen failed" << std::endl; closesock(server_fd_); server_fd_=-1; running_=false; return; }
  std::cout << "[rest] HTTP server started on :" << port_ << std::endl;

  while (running_) {
    sockaddr_in caddr{}; socklen_t clen = sizeof(caddr);
#ifdef _WIN32
    int cfd = ::accept(server_fd_, (sockaddr*)&caddr, &clen);
    if (cfd == INVALID_SOCKET) { continue; }
#else
    int cfd = ::accept(server_fd_, (sockaddr*)&caddr, &clen);
    if (cfd < 0) { continue; }
#endif
    // read headers
#ifdef _WIN32
    int rcv_ms = 2000; ::setsockopt(cfd, SOL_SOCKET, SO_RCVTIMEO, (const char*)&rcv_ms, sizeof(rcv_ms));
#else
    struct timeval tv; tv.tv_sec = 2; tv.tv_usec = 0; ::setsockopt(cfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif
    std::string req; req.reserve(4096);
    char buf[2048]; bool header_done=false; size_t max=1<<20; size_t content_length=0;
    for (;;) {
#ifdef _WIN32
      int n = ::recv(cfd, buf, sizeof(buf), 0);
#else
      ssize_t n = ::recv(cfd, buf, sizeof(buf), 0);
#endif
      if (n<=0) break; req.append(buf, buf+n);
      auto p = req.find("\r\n\r\n");
      if (p != std::string::npos) { header_done = true; break; }
      if (req.size() > max) break;
    }
    if (!header_done) { closesock(cfd); continue; }
    // parse request line and headers
    std::string method, path;
    {
      auto line_end = req.find("\r\n");
      if (line_end != std::string::npos) {
        std::istringstream iss(req.substr(0,line_end));
        std::string http; iss >> method >> path >> http;
      }
      // headers for content-length
      auto hdrs = req.substr(0, req.find("\r\n\r\n")+2);
      auto pos = hdrs.find("Content-Length:");
      if (pos == std::string::npos) pos = hdrs.find("content-length:");
      if (pos != std::string::npos) {
        auto end = hdrs.find("\r\n", pos);
        auto val = hdrs.substr(pos, end-pos);
        auto cpos = val.find(":"); if (cpos != std::string::npos) {
          try { content_length = (size_t)std::stoll(val.substr(cpos+1)); } catch(...) {}
        }
      }
    }
    // read body if any
    std::string body;
    auto after = req.find("\r\n\r\n");
    if (after != std::string::npos) {
      size_t already = req.size() - (after+4);
      body.assign(req.data()+after+4, already);
      while (body.size() < content_length && body.size() < max) {
#ifdef _WIN32
        int n2 = ::recv(cfd, buf, sizeof(buf), 0);
#else
        ssize_t n2 = ::recv(cfd, buf, sizeof(buf), 0);
#endif
        if (n2 <= 0) break;
        body.append(buf, buf+n2);
      }
    }
    // parse query
    auto query = parseQuery(path);
    // strip query from path
    auto qpos = path.find('?'); if (qpos != std::string::npos) path = path.substr(0, qpos);

    int status = 200; std::string ctype = "application/json; charset=utf-8";
    std::string resp;
    try {
      resp = handler_ ? handler_(method, path, query, body, &status, &ctype) : std::string("{}");
    } catch (...) {
      status = 500; resp = "{\"success\":false,\"message\":\"internal error\"}"; ctype = "application/json; charset=utf-8";
    }

    std::ostringstream oss;
    if (status == 200) oss << "HTTP/1.1 200 OK\r\n";
    else if (status == 400) oss << "HTTP/1.1 400 Bad Request\r\n";
    else if (status == 404) oss << "HTTP/1.1 404 Not Found\r\n";
    else if (status == 405) oss << "HTTP/1.1 405 Method Not Allowed\r\n";
    else oss << "HTTP/1.1 500 Internal Server Error\r\n";
    oss << "Content-Type: " << ctype << "\r\n";
    oss << "Connection: close\r\n";
    oss << "Content-Length: " << resp.size() << "\r\n\r\n";
    oss << resp;
    auto s = oss.str();
#ifdef _WIN32
    ::send(cfd, s.c_str(), (int)s.size(), 0);
#else
    ::send(cfd, s.c_str(), s.size(), 0);
#endif
    closesock(cfd);
  }

  if (server_fd_ >= 0) { closesock(server_fd_); server_fd_=-1; }
#ifdef _WIN32
  WSACleanup();
#endif
}

std::unordered_map<std::string,std::string> RestServer::parseQuery(const std::string& path) {
  std::unordered_map<std::string,std::string> q;
  auto p = path.find('?'); if (p == std::string::npos) return q;
  auto s = path.substr(p+1);
  size_t pos = 0;
  while (pos < s.size()) {
    auto eq = s.find('=', pos);
    auto amp = s.find('&', pos);
    if (eq == std::string::npos) break;
    std::string k = s.substr(pos, eq-pos);
    std::string v = (amp==std::string::npos) ? s.substr(eq+1) : s.substr(eq+1, amp-eq-1);
    q[urlDecode(k)] = urlDecode(v);
    if (amp == std::string::npos) break;
    pos = amp + 1;
  }
  return q;
}

std::string RestServer::urlDecode(const std::string& in) {
  std::string out; out.reserve(in.size());
  for (size_t i=0;i<in.size();++i) {
    if (in[i] == '+') out.push_back(' ');
    else if (in[i] == '%' && i+2 < in.size()) {
      auto hex = in.substr(i+1,2);
      char c = static_cast<char>(std::strtol(hex.c_str(), nullptr, 16));
      out.push_back(c); i += 2;
    } else out.push_back(in[i]);
  }
  return out;
}

void RestServer::WakeAccept() {
  int fd = static_cast<int>(::socket(AF_INET, SOCK_STREAM, 0)); if (fd < 0) return;
  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_port = htons((uint16_t)port_);
  inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
  ::connect(fd, (sockaddr*)&addr, sizeof(addr));
  closesock(fd);
}

std::string jsonEscape(const std::string& s) {
  std::string o; o.reserve(s.size()+8);
  for (char c : s) {
    switch(c) {
      case '"': o += "\\\""; break;
      case '\\': o += "\\\\"; break;
      case '\b': o += "\\b"; break;
      case '\f': o += "\\f"; break;
      case '\n': o += "\\n"; break;
      case '\r': o += "\\r"; break;
      case '\t': o += "\\t"; break;
      default:
        if ((unsigned char)c < 0x20) {
          char buf[7]; std::snprintf(buf, sizeof(buf), "\\u%04x", (unsigned int)(unsigned char)c); o += buf;
        } else o.push_back(c);
    }
  }
  return o;
}

} // namespace vsm::rest

