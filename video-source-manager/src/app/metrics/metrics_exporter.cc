#include "app/metrics/metrics_exporter.h"
#include <iostream>
#include <sstream>
#include <cstring>

#ifdef _WIN32
#include <winsock2.h>
#include <ws2tcpip.h>
#pragma comment(lib, "ws2_32.lib")
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
  if (th_.joinable()) th_.join();
}

void MetricsExporter::ServerLoop() {
#ifdef _WIN32
  WSADATA wsaData; WSAStartup(MAKEWORD(2,2), &wsaData);
#endif
  int server_fd = static_cast<int>(::socket(AF_INET, SOCK_STREAM, 0));
  if (server_fd < 0) {
    std::cerr << "[metrics] failed to create socket" << std::endl;
    running_ = false; return;
  }

  int opt = 1;
#ifdef _WIN32
  ::setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, (const char*)&opt, sizeof(opt));
#else
  ::setsockopt(server_fd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));
#endif

  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_addr.s_addr = INADDR_ANY; addr.sin_port = htons((uint16_t)port_);
  if (::bind(server_fd, (sockaddr*)&addr, sizeof(addr)) < 0) {
    std::cerr << "[metrics] bind failed on port " << port_ << std::endl;
#ifdef _WIN32
    ::closesocket(server_fd);
    WSACleanup();
#else
    ::close(server_fd);
#endif
    running_ = false; return;
  }
  if (::listen(server_fd, 8) < 0) {
    std::cerr << "[metrics] listen failed" << std::endl;
#ifdef _WIN32
    ::closesocket(server_fd);
    WSACleanup();
#else
    ::close(server_fd);
#endif
    running_ = false; return;
  }

  std::cout << "[metrics] HTTP server started on :" << port_ << std::endl;
  while (running_) {
    sockaddr_in caddr{}; socklen_t clen = sizeof(caddr);
#ifdef _WIN32
    int cfd = ::accept(server_fd, (sockaddr*)&caddr, &clen);
    if (cfd == INVALID_SOCKET) { continue; }
#else
    int cfd = ::accept(server_fd, (sockaddr*)&caddr, &clen);
    if (cfd < 0) { continue; }
#endif
    char buf[2048];
#ifdef _WIN32
    int n = ::recv(cfd, buf, sizeof(buf)-1, 0);
#else
    ssize_t n = ::recv(cfd, buf, sizeof(buf)-1, 0);
#endif
    if (n <= 0) {
#ifdef _WIN32
      ::closesocket(cfd);
#else
      ::close(cfd);
#endif
      continue;
    }
    buf[n] = 0;
    // Very simple parse: check for GET /metrics
    std::string req(buf);
    bool is_metrics = req.rfind("GET /metrics", 0) == 0 || req.find("GET /metrics ") != std::string::npos;
    std::string body;
    int status = 200;
    if (is_metrics) {
      try { body = builder_ ? builder_() : std::string(""); } catch(...) { body.clear(); }
      if (body.empty()) body = "# HELP vsm_exporter_up 1 when exporter is healthy\n# TYPE vsm_exporter_up gauge\nvsm_exporter_up 1\n";
    } else {
      status = 404; body = "not found";
    }
    std::ostringstream oss;
    oss << "HTTP/1.1 " << (status==200?"200 OK":"404 Not Found") << "\r\n";
    oss << "Content-Type: text/plain; version=0.0.4\r\n";
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
  ::closesocket(server_fd);
  WSACleanup();
#else
  ::close(server_fd);
#endif
}

} // namespace vsm::metrics

