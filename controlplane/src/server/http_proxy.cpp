#include "controlplane/http_proxy.hpp"
#include <sstream>
#include <vector>
#include <algorithm>
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#endif

namespace controlplane {

static std::string pick_header(const std::string& headers, const char* key) {
  // naive case-sensitive search; return value without leading spaces
  auto p = headers.find(key);
  if (p == std::string::npos) return {};
  p += std::strlen(key);
  auto e = headers.find("\r\n", p);
  auto v = headers.substr(p, e==std::string::npos? std::string::npos : e-p);
  size_t b=0; while (b<v.size() && (v[b]==' '||v[b]=='\t')) ++b; return v.substr(b);
}

static bool send_all(SOCKET s, const char* buf, int len) {
  int off = 0; while (off < len) {
    int n = send(s, buf + off, len - off, 0);
    if (n <= 0) return false; off += n;
  } return true;
}

bool proxy_http_simple(const std::string& host,
                       int port,
                       const std::string& method,
                       const std::string& path_and_query,
                       const std::string& in_headers,
                       const std::string& body,
                       HttpResponse* out,
                       std::string* out_location) {
#ifndef _WIN32
  (void)host; (void)port; (void)method; (void)path_and_query; (void)in_headers; (void)body; (void)out; (void)out_location;
  return false;
#else
  out->status = 502; out->contentType = "application/json"; out->body = "{}"; out->extraHeaders.clear();
  if (out_location) *out_location = {};
  SOCKET s = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
  if (s == INVALID_SOCKET) return false;
  sockaddr_in addr{}; addr.sin_family = AF_INET; addr.sin_port = htons(static_cast<u_short>(port));
  if (inet_pton(AF_INET, host.c_str(), &addr.sin_addr) != 1) { closesocket(s); return false; }
  if (connect(s, (sockaddr*)&addr, sizeof(addr)) != 0) { closesocket(s); return false; }

  std::ostringstream req;
  req << method << " " << path_and_query << " HTTP/1.1\r\n";
  req << "Host: " << host << ":" << port << "\r\n";
  // pick content-type from incoming headers if present
  auto ct = pick_header(in_headers, "Content-Type:");
  if (!ct.empty()) req << "Content-Type: " << ct << "\r\n";
  req << "Connection: close\r\n";
  if (!body.empty()) req << "Content-Length: " << body.size() << "\r\n";
  req << "\r\n";
  if (!body.empty()) req.write(body.data(), static_cast<std::streamsize>(body.size()));
  auto str = req.str();
  if (!send_all(s, str.data(), static_cast<int>(str.size()))) { closesocket(s); return false; }

  std::string resp; resp.reserve(4096);
  char buf[4096];
  for (;;) {
    int n = recv(s, buf, sizeof(buf), 0);
    if (n <= 0) break; resp.append(buf, buf + n);
  }
  closesocket(s);
  auto h_end = resp.find("\r\n\r\n");
  if (h_end == std::string::npos) return false;
  std::string head = resp.substr(0, h_end);
  std::string body_out = resp.substr(h_end + 4);
  // status
  int status = 502;
  {
    auto sp1 = head.find(' ');
    if (sp1 != std::string::npos) {
      auto sp2 = head.find(' ', sp1+1);
      if (sp2 != std::string::npos) {
        try { status = std::stoi(head.substr(sp1+1, sp2-sp1-1)); } catch (...) {}
      }
    }
  }
  // headers parse (very small)
  std::string contentType = "application/octet-stream";
  std::string location;
  {
    auto pos = head.find("\r\n");
    while (true) {
      if (pos == std::string::npos) break;
      auto next = head.find("\r\n", pos+2);
      if (next == std::string::npos) break;
      auto line = head.substr(pos+2, next-(pos+2));
      pos = next;
      auto cpos = line.find(':'); if (cpos == std::string::npos) continue;
      auto key = line.substr(0, cpos); for (auto& c : key) c = (char)tolower((unsigned char)c);
      auto val = line.substr(cpos+1); size_t b=0; while (b<val.size() && (val[b]==' '||val[b]=='\t')) ++b; val = val.substr(b);
      if (key == "content-type") contentType = val;
      else if (key == "location") location = val;
    }
  }
  out->status = status;
  out->contentType = contentType.empty()? "application/octet-stream" : contentType;
  out->body = std::move(body_out);
  if (out_location) *out_location = std::move(location);
  return true;
#endif
}

} // namespace controlplane

