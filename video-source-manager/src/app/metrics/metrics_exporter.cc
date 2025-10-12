#include "app/metrics/metrics_exporter.h"
#include <iostream>
#include <sstream>
#include <cstring>
#include <cstdlib>
#include <algorithm>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <sys/types.h>
#include <sys/socket.h>
#include <netinet/in.h>
#include <arpa/inet.h>
#include <unistd.h>
#endif

namespace vsm::metrics {

MetricsExporter::MetricsExporter(int port, BuilderFn builder)
  : port_(port), builder_(std::move(builder)) {}

MetricsExporter::~MetricsExporter() { Stop(); }

bool MetricsExporter::Start() {
  if (running_) return true;
  running_ = true;
  th_ = std::thread(&MetricsExporter::ServerLoop, this);
  return true;
}

void MetricsExporter::Stop() {
  if (!running_) return;
  running_ = false;
  // 尝试唤醒阻塞中的 accept，确保线程可退出
  try { WakeAccept(); } catch (...) {}
  if (th_.joinable()) th_.join();
}

void MetricsExporter::ServerLoop() {
#ifdef _WIN32
  WSADATA wsaData; WSAStartup(MAKEWORD(2,2), &wsaData);
#endif
  // 允许通过环境变量覆盖端口
  if (const char* p = std::getenv("VSM_METRICS_PORT")) {
    try { int v = std::stoi(p); if (v > 0 && v < 65536) port_ = v; } catch (...) {}
  }
  server_fd_ = static_cast<int>(::socket(AF_INET, SOCK_STREAM, 0));
  if (server_fd_ < 0) {
    std::cerr << "[metrics] failed to create socket" << std::endl;
    running_ = false; return;
  }

  int opt = 1;
#ifdef _WIN32
  ::setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
  ::setsockopt(server_fd_, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_addr.s_addr = INADDR_ANY; addr.sin_port = htons((uint16_t)port_);
  if (::bind(server_fd_, (sockaddr*)&addr, sizeof(addr)) < 0) {
    std::cerr << "[metrics] bind failed on port " << port_ << std::endl;
#ifdef _WIN32
    ::closesocket(server_fd_);
    WSACleanup();
#else
    ::close(server_fd_);
#endif
    server_fd_ = -1;
    running_ = false; return;
  }
  if (::listen(server_fd_, 16) < 0) {
    std::cerr << "[metrics] listen failed" << std::endl;
#ifdef _WIN32
    ::closesocket(server_fd_);
    WSACleanup();
#else
    ::close(server_fd_);
#endif
    server_fd_ = -1;
    running_ = false; return;
  }

  std::cout << "[metrics] HTTP server started on :" << port_ << std::endl;
  while (running_) {
    sockaddr_in caddr{}; socklen_t clen = sizeof(caddr);
#ifdef _WIN32
    int cfd = ::accept(server_fd_, (sockaddr*)&caddr, &clen);
    if (cfd == INVALID_SOCKET) { continue; }
#else
    int cfd = ::accept(server_fd_, (sockaddr*)&caddr, &clen);
    if (cfd < 0) { continue; }
#endif
    // 持续读取直到头结束（\r\n\r\n）或达到上限
    std::string req; req.reserve(2048);
    const size_t kMaxReq = 8192; bool header_done = false;
#ifdef _WIN32
    int rcv_ms = 1000; ::setsockopt(cfd, SOL_SOCKET, SO_RCVTIMEO, (const char*)&rcv_ms, sizeof(rcv_ms));
#else
    struct timeval tv; tv.tv_sec = 1; tv.tv_usec = 0; ::setsockopt(cfd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
#endif
    char buf[1024];
    for (;;) {
#ifdef _WIN32
      int n = ::recv(cfd, buf, sizeof(buf), 0);
#else
      ssize_t n = ::recv(cfd, buf, sizeof(buf), 0);
#endif
      if (n <= 0) break;
      req.append(buf, buf + n);
      if (req.find("\r\n\r\n") != std::string::npos) { header_done = true; break; }
      if (req.size() > kMaxReq) break;
    }
    if (!header_done) {
#ifdef _WIN32
      ::closesocket(cfd);
#else
      ::close(cfd);
#endif
      continue;
    }
    // 解析请求行 METHOD PATH HTTP/..
    std::string method, path;
    auto line_end = req.find("\r\n");
    if (line_end != std::string::npos) {
      std::string line = req.substr(0, line_end);
      std::istringstream iss(line);
      iss >> method >> path; // ignore version
    }
    std::string lower_method = method; std::transform(lower_method.begin(), lower_method.end(), lower_method.begin(), ::tolower);
    auto qpos = path.find('?'); if (qpos != std::string::npos) path = path.substr(0, qpos);
    bool is_metrics = (lower_method == "get" || lower_method == "head") && (path == "/metrics" || path == "/metrics/");
    std::string body;
    int status = 200;
    if (is_metrics) {
      try { body = builder_ ? builder_() : std::string(""); } catch(...) { body.clear(); }
      if (body.empty()) body = "# HELP vsm_exporter_up 1 when exporter is healthy\n# TYPE vsm_exporter_up gauge\nvsm_exporter_up 1\n";
      if (lower_method == "head") body.clear();
    } else {
      status = (lower_method == "get" || lower_method == "head") ? 404 : 405;
      body = (status==405? "method not allowed" : "not found");
    }
    std::ostringstream oss;
    if (status == 405) {
      oss << "HTTP/1.1 405 Method Not Allowed\r\n";
    } else {
      oss << "HTTP/1.1 " << (status==200?"200 OK":"404 Not Found") << "\r\n";
    }
    oss << "Content-Type: text/plain; version=0.0.4; charset=utf-8\r\n";
    oss << "Connection: close\r\n";
    oss << "Content-Length: " << body.size() << "\r\n\r\n";
    oss << body;
    auto resp = oss.str();
#ifdef _WIN32
    ::send(cfd, resp.c_str(), (int)resp.size(), 0);
    ::closesocket(cfd);
#else
    ::send(cfd, resp.c_str(), resp.size(), 0);
    ::close(cfd);
#endif
  }

#ifdef _WIN32
  if (server_fd_ >= 0) { ::closesocket(server_fd_); server_fd_ = -1; WSACleanup(); }
#else
  if (server_fd_ >= 0) { ::close(server_fd_); server_fd_ = -1; }
#endif
}

} // namespace vsm::metrics

// Wake helper implementation
namespace vsm::metrics {
void MetricsExporter::WakeAccept() {
  // connect to localhost to unblock accept if needed
  int fd = static_cast<int>(::socket(AF_INET, SOCK_STREAM, 0));
  if (fd < 0) return;
  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_port = htons((uint16_t)port_);
#ifdef _WIN32
  inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
  ::connect(fd, (sockaddr*)&addr, sizeof(addr));
  ::closesocket(fd);
#else
  inet_pton(AF_INET, "127.0.0.1", &addr.sin_addr);
  ::connect(fd, (sockaddr*)&addr, sizeof(addr));
  ::close(fd);
#endif
}
} // namespace vsm::metrics
