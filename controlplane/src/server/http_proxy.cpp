#include "controlplane/http_proxy.hpp"
#include <sstream>
#include <vector>
#include <algorithm>
#include <map>
#include <cctype>
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#  pragma comment(lib, "Ws2_32.lib")
#else
#  include <sys/types.h>
#  include <sys/socket.h>
#  include <netdb.h>
#  include <arpa/inet.h>
#  include <unistd.h>
#  include <netinet/tcp.h>
#  include <iostream>
#endif

namespace controlplane {

static inline std::string to_lower(std::string s) {
  for (auto& c : s) c = (char)std::tolower((unsigned char)c); return s;
}

static std::map<std::string, std::string> parse_headers_ci(const std::string& headers) {
  std::map<std::string, std::string> m;
  size_t pos = 0; while (true) {
    auto next = headers.find("\r\n", pos);
    if (next == std::string::npos) break;
    auto line = headers.substr(pos, next-pos);
    pos = next + 2;
    auto cpos = line.find(':'); if (cpos == std::string::npos) continue;
    auto key = to_lower(line.substr(0, cpos));
    auto val = line.substr(cpos+1); size_t b=0; while (b<val.size() && (val[b]==' '||val[b]=='\t')) ++b; val = val.substr(b);
    if (!key.empty()) m[key] = val;
  }
  return m;
}

#ifdef _WIN32
using sock_t = SOCKET;
static bool send_all(sock_t s, const char* buf, int len) {
  int off = 0; while (off < len) { int n = send(s, buf+off, len-off, 0); if (n <= 0) return false; off += n; } return true;
}

static bool connect_with_timeout(const std::string& host, int port, sock_t& out, int ms_timeout) {
  out = INVALID_SOCKET;
  addrinfo hints{}; hints.ai_socktype = SOCK_STREAM; hints.ai_family = AF_UNSPEC; hints.ai_protocol = IPPROTO_TCP;
  std::ostringstream os; os << host << ":" << port;
  addrinfo* res = nullptr;
  if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) != 0 || !res) return false;
  bool ok = false;
  for (auto p = res; p != nullptr; p = p->ai_next) {
    sock_t s = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
    if (s == INVALID_SOCKET) continue;
    DWORD tv = (ms_timeout > 0 ? (DWORD)ms_timeout : 0);
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, (char*)&tv, sizeof(tv));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, (char*)&tv, sizeof(tv));
    BOOL yes = TRUE; setsockopt(s, IPPROTO_TCP, TCP_NODELAY, (char*)&yes, sizeof(yes));
    if (::connect(s, p->ai_addr, (int)p->ai_addrlen) == 0) { out = s; ok = true; break; }
    closesocket(s);
  }
  freeaddrinfo(res);
  return ok;
}
#endif

static bool dechunk(const std::string& in, std::string& out) {
  size_t i = 0; out.clear();
  while (true) {
    size_t line_end = in.find("\r\n", i); if (line_end == std::string::npos) return false;
    std::string szhex = in.substr(i, line_end - i); auto sc = szhex.find(';'); if (sc != std::string::npos) szhex = szhex.substr(0, sc);
    size_t chunk_size = 0; try { chunk_size = std::stoul(szhex, nullptr, 16); } catch (...) { return false; }
    i = line_end + 2; if (chunk_size == 0) { return true; }
    if (i + chunk_size > in.size()) return false; out.append(in.data() + i, chunk_size); i += chunk_size;
    if (i + 2 > in.size() || in[i] != '\r' || in[i+1] != '\n') return false; i += 2;
  }
}

static std::string host_header_value(const std::string& host, int port, int /*family_hint*/ = 0) {
  // On non-Windows builds we avoid relying on AF_* macros; bracket IPv6 literals by detecting ':'
  bool need_bracket = (host.find(':') != std::string::npos);
  std::ostringstream os; if (need_bracket) os << "[" << host << "]:" << port; else os << host << ":" << port; return os.str();
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
  out->status = 502; out->contentType = "application/json"; out->body = "{}"; out->extraHeaders.clear(); if (out_location) *out_location = {};
  // POSIX implementation using BSD sockets
  // Debug hint: log basic proxy target when talking to Agent service
  bool debug_agent = (host == "agent");
  if (debug_agent) {
    std::cerr << "[http_proxy] proxy_http_simple host=" << host
              << " port=" << port
              << " method=" << method
              << " path=" << path_and_query
              << " body_len=" << body.size() << std::endl;
  }
  int sock = -1;
  struct addrinfo hints{}; hints.ai_socktype = SOCK_STREAM; hints.ai_family = AF_UNSPEC; hints.ai_protocol = IPPROTO_TCP;
  struct addrinfo* res = nullptr;
  if (getaddrinfo(host.c_str(), std::to_string(port).c_str(), &hints, &res) != 0 || !res) {
    if (debug_agent) {
      std::cerr << "[http_proxy] getaddrinfo failed for host=" << host
                << " port=" << port << std::endl;
    }
    return false;
  }
  bool ok = false;
  for (auto p = res; p != nullptr; p = p->ai_next) {
    int s = ::socket(p->ai_family, p->ai_socktype, p->ai_protocol);
    if (s < 0) continue;
    // Timeouts：默认 30 秒；对 Agent 服务（host == "agent"）进一步放宽到 120 秒，
    // 避免长上下文 LLM/工具调用导致的长响应被误判为错误。
    struct timeval tv;
    tv.tv_sec = debug_agent ? 120 : 30;
    tv.tv_usec = 0;
    setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));
    int yes = 1; setsockopt(s, IPPROTO_TCP, TCP_NODELAY, &yes, sizeof(yes));
    if (::connect(s, p->ai_addr, p->ai_addrlen) == 0) { sock = s; ok = true; break; }
    ::close(s);
  }
  freeaddrinfo(res);
  if (!ok) {
    if (debug_agent) {
      std::cerr << "[http_proxy] connect failed for host=" << host
                << " port=" << port << std::endl;
    }
    return false;
  }

  auto req_h = parse_headers_ci(in_headers);
  std::map<std::string, std::string> fwd_h;
  auto it = req_h.find("authorization"); if (it != req_h.end()) fwd_h["Authorization"] = it->second;
  it = req_h.find("content-type"); if (it != req_h.end()) fwd_h["Content-Type"] = it->second;
  it = req_h.find("accept"); if (it != req_h.end()) fwd_h["Accept"] = it->second;
  it = req_h.find("if-match"); if (it != req_h.end()) fwd_h["If-Match"] = it->second;
  if (to_lower(method) == "post") fwd_h["Accept"] = "application/sdp";
  fwd_h["Accept-Encoding"] = "identity";
  fwd_h["Connection"] = "close";

  std::ostringstream req;
  req << method << " " << path_and_query << " HTTP/1.1\r\n";
  req << "Host: " << host_header_value(host, port) << "\r\n";
  for (const auto& kv : fwd_h) req << kv.first << ": " << kv.second << "\r\n";
  if (!body.empty()) req << "Content-Length: " << body.size() << "\r\n";
  req << "\r\n";
  if (!body.empty()) req.write(body.data(), static_cast<std::streamsize>(body.size()));
  auto str = req.str();
  {
    size_t off = 0; const char* buf = str.data(); size_t len = str.size();
    while (off < len) {
      ssize_t n = ::send(sock, buf + off, len - off, 0);
      if (n <= 0) { ::close(sock); return false; }
      off += static_cast<size_t>(n);
    }
  }

  std::string resp; resp.reserve(4096);
  char buf[4096]; for (;;) { ssize_t n = ::recv(sock, buf, sizeof(buf), 0); if (n <= 0) break; resp.append(buf, buf+n); }
  ::close(sock);

  auto h_end = resp.find("\r\n\r\n");
  if (h_end == std::string::npos) {
    if (debug_agent) {
      std::cerr << "[http_proxy] invalid HTTP response (no CRLFCRLF), size="
                << resp.size() << std::endl;
    }
    return false;
  }
  std::string head = resp.substr(0, h_end); std::string body_raw = resp.substr(h_end + 4);
  // status line
  int status = 502; { auto sp1 = head.find(' '); if (sp1 != std::string::npos) { auto sp2 = head.find(' ', sp1+1); if (sp2 != std::string::npos) { try { status = std::stoi(head.substr(sp1+1, sp2-sp1-1)); } catch (...) {} } } }
  // headers
  std::map<std::string, std::string> resp_h; std::string contentType = "application/octet-stream"; std::string location; bool is_chunked = false;
  { size_t pos = 0; auto line_end = head.find("\r\n", pos); if (line_end == std::string::npos) return false; pos = line_end; // skip status line
    while (true) { auto next = head.find("\r\n", pos+2); if (next == std::string::npos) break; auto line = head.substr(pos+2, next-(pos+2)); pos = next; auto cpos = line.find(':'); if (cpos==std::string::npos) continue; auto key = to_lower(line.substr(0, cpos)); auto val = line.substr(cpos+1); size_t b=0; while (b<val.size() && (val[b]==' '||val[b]=='\t')) ++b; val = val.substr(b); resp_h[key]=val; if (key=="content-type") contentType = val; else if (key=="location") location = val; else if (key=="transfer-encoding") { auto vl=to_lower(val); if (vl.find("chunked")!=std::string::npos) is_chunked=true; } }
  }
  std::string body_out;
  if (is_chunked) { if (!dechunk(body_raw, body_out)) body_out = body_raw; }
  else { body_out = std::move(body_raw); }

  out->status = status;
  out->contentType = contentType.empty()? "application/octet-stream" : contentType;
  out->body = std::move(body_out);
  // propagate important headers to caller via extraHeaders (they will be exposed to browser later)
  if (!location.empty()) {
    if (out_location) *out_location = location;
    // Also surface original Location header to caller; main.cpp may rewrite it later
    out->extraHeaders += std::string("Location: ") + location + "\r\n";
  }
  if (resp_h.count("etag")) out->extraHeaders += std::string("ETag: ") + resp_h["etag"] + "\r\n";
  if (resp_h.count("accept-patch")) out->extraHeaders += std::string("Accept-Patch: ") + resp_h["accept-patch"] + "\r\n";
  return true;
#else
  out->status = 502; out->contentType = "application/json"; out->body = "{}"; out->extraHeaders.clear(); if (out_location) *out_location = {};
  sock_t s = INVALID_SOCKET; if (!connect_with_timeout(host, port, s, 5000)) return false;

  auto req_h = parse_headers_ci(in_headers);
  std::map<std::string, std::string> fwd_h;
  auto it = req_h.find("authorization"); if (it != req_h.end()) fwd_h["Authorization"] = it->second;
  it = req_h.find("content-type"); if (it != req_h.end()) fwd_h["Content-Type"] = it->second;
  it = req_h.find("accept"); if (it != req_h.end()) fwd_h["Accept"] = it->second;
  it = req_h.find("if-match"); if (it != req_h.end()) fwd_h["If-Match"] = it->second;
  if (to_lower(method) == "post") fwd_h["Accept"] = "application/sdp";
  fwd_h["Accept-Encoding"] = "identity"; // avoid gzip/chunked complexities
  fwd_h["Connection"] = "close";

  std::ostringstream req;
  req << method << " " << path_and_query << " HTTP/1.1\r\n";
  req << "Host: " << host_header_value(host, port) << "\r\n";
  for (const auto& kv : fwd_h) req << kv.first << ": " << kv.second << "\r\n";
  if (!body.empty()) req << "Content-Length: " << body.size() << "\r\n";
  req << "\r\n";
  if (!body.empty()) req.write(body.data(), static_cast<std::streamsize>(body.size()));
  auto str = req.str(); if (!send_all(s, str.data(), static_cast<int>(str.size()))) { closesocket(s); return false; }

  std::string resp; resp.reserve(4096);
  char buf[4096]; for (;;) { int n = recv(s, buf, sizeof(buf), 0); if (n <= 0) break; resp.append(buf, buf+n); }
  closesocket(s);
  auto h_end = resp.find("\r\n\r\n"); if (h_end == std::string::npos) return false;
  std::string head = resp.substr(0, h_end); std::string body_raw = resp.substr(h_end + 4);
  // status line
  int status = 502; { auto sp1 = head.find(' '); if (sp1 != std::string::npos) { auto sp2 = head.find(' ', sp1+1); if (sp2 != std::string::npos) { try { status = std::stoi(head.substr(sp1+1, sp2-sp1-1)); } catch (...) {} } } }
  // headers
  std::map<std::string, std::string> resp_h; std::string contentType = "application/octet-stream"; std::string location; bool is_chunked = false;
  { size_t pos = 0; auto line_end = head.find("\r\n", pos); if (line_end == std::string::npos) return false; pos = line_end; // skip status line
    while (true) { auto next = head.find("\r\n", pos+2); if (next == std::string::npos) break; auto line = head.substr(pos+2, next-(pos+2)); pos = next; auto cpos = line.find(':'); if (cpos==std::string::npos) continue; auto key = to_lower(line.substr(0, cpos)); auto val = line.substr(cpos+1); size_t b=0; while (b<val.size() && (val[b]==' '||val[b]=='\t')) ++b; val = val.substr(b); resp_h[key]=val; if (key=="content-type") contentType = val; else if (key=="location") location = val; else if (key=="transfer-encoding") { auto vl=to_lower(val); if (vl.find("chunked")!=std::string::npos) is_chunked=true; } }
  }
  std::string body_out;
  if (is_chunked) { if (!dechunk(body_raw, body_out)) body_out = body_raw; }
  else { body_out = std::move(body_raw); }

  out->status = status;
  out->contentType = contentType.empty()? "application/octet-stream" : contentType;
  out->body = std::move(body_out);
  // propagate important headers to caller via extraHeaders (they will be exposed to browser later)
  if (!location.empty()) {
    if (out_location) *out_location = location;
    out->extraHeaders += std::string("Location: ") + location + "\r\n";
  }
  if (resp_h.count("etag")) out->extraHeaders += std::string("ETag: ") + resp_h["etag"] + "\r\n";
  if (resp_h.count("accept-patch")) out->extraHeaders += std::string("Accept-Patch: ") + resp_h["accept-patch"] + "\r\n";
  return true;
#endif
}

} // namespace controlplane
