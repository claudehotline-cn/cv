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
    std::thread([this,cfd]() {
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
      if (!header_done) { closesock(cfd); return; }
      std::string method, path;
      {
        auto line_end = req.find("\r\n");
        if (line_end != std::string::npos) {
          std::istringstream iss(req.substr(0,line_end));
          std::string http; iss >> method >> path >> http;
        }
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
      auto query = parseQuery(path);
      auto qpos = path.find('?'); if (qpos != std::string::npos) path = path.substr(0, qpos);

      int status = 200; std::string ctype = "application/json; charset=utf-8";
      std::string resp;
      try { resp = handler_ ? handler_(method, path, query, body, &status, &ctype) : std::string("{}"); }
      catch (...) { status = 500; resp = "{\"success\":false,\"message\":\"internal error\"}"; ctype = "application/json; charset=utf-8"; }

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
    }).detach();
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

namespace {
struct JsonCursor { const char* p; const char* end; };
static inline void skipWS(JsonCursor& c){ while(c.p<c.end && (*c.p==' '||*c.p=='\n'||*c.p=='\r'||*c.p=='\t')) ++c.p; }
static bool parseHex4(JsonCursor& c, unsigned& out){ out=0; for(int i=0;i<4;++i){ if(c.p>=c.end) return false; char ch=*c.p++; unsigned v=0; if(ch>='0'&&ch<='9') v=ch-'0'; else if(ch>='a'&&ch<='f') v=10+ch-'a'; else if(ch>='A'&&ch<='F') v=10+ch-'A'; else return false; out=(out<<4)|v; } return true; }
static void appendUtf8(unsigned cp, std::string& out){ if(cp<=0x7F) out.push_back((char)cp); else if(cp<=0x7FF){ out.push_back((char)(0xC0|((cp>>6)&0x1F))); out.push_back((char)(0x80|(cp&0x3F))); } else if(cp<=0xFFFF){ out.push_back((char)(0xE0|((cp>>12)&0x0F))); out.push_back((char)(0x80|((cp>>6)&0x3F))); out.push_back((char)(0x80|(cp&0x3F))); } else { out.push_back((char)(0xF0|((cp>>18)&0x07))); out.push_back((char)(0x80|((cp>>12)&0x3F))); out.push_back((char)(0x80|((cp>>6)&0x3F))); out.push_back((char)(0x80|(cp&0x3F))); } }
static bool parseString(JsonCursor& c, std::string& out){ if(c.p>=c.end || *c.p!='"') return false; ++c.p; while(c.p<c.end){ char ch=*c.p++; if(ch=='"') return true; if(ch=='\\'){ if(c.p>=c.end) return false; char e=*c.p++; switch(e){ case '"': out.push_back('"'); break; case '\\': out.push_back('\\'); break; case '/': out.push_back('/'); break; case 'b': out.push_back('\b'); break; case 'f': out.push_back('\f'); break; case 'n': out.push_back('\n'); break; case 'r': out.push_back('\r'); break; case 't': out.push_back('\t'); break; case 'u': { unsigned cp; if(!parseHex4(c,cp)) return false; // surrogate pairs
            if(cp>=0xD800 && cp<=0xDBFF){ if(c.p+2<=c.end && *c.p=='\\' && *(c.p+1)=='u'){ c.p+=2; unsigned cp2; if(!parseHex4(c,cp2)) return false; if(cp2>=0xDC00 && cp2<=0xDFFF){ unsigned u = 0x10000 + (((cp-0xD800)<<10)|(cp2-0xDC00)); appendUtf8(u,out); break; } }
            }
            appendUtf8(cp,out); break; }
          default: return false; }
        } else { out.push_back(ch); }
      }
      return false;
}
static bool parseLiteral(JsonCursor& c, const char* lit, std::string* out){ const char* q=lit; const char* start=c.p; while(*q && c.p<c.end && *c.p==*q){ ++c.p; ++q; } if(*q==0){ if(out) *out=std::string(start,c.p-start); return true; } c.p=start; return false; }
static bool parseNumber(JsonCursor& c, std::string& out){ const char* start=c.p; if(c.p<c.end && (*c.p=='-'||*c.p=='+')) ++c.p; if(c.p<c.end && *c.p=='0'){ ++c.p; } else { if(c.p>=c.end || !std::isdigit((unsigned char)*c.p)) return false; while(c.p<c.end && std::isdigit((unsigned char)*c.p)) ++c.p; }
 if(c.p<c.end && *c.p=='.'){ ++c.p; if(c.p>=c.end || !std::isdigit((unsigned char)*c.p)) return false; while(c.p<c.end && std::isdigit((unsigned char)*c.p)) ++c.p; }
 if(c.p<c.end && (*c.p=='e'||*c.p=='E')){ ++c.p; if(c.p<c.end && (*c.p=='+'||*c.p=='-')) ++c.p; if(c.p>=c.end || !std::isdigit((unsigned char)*c.p)) return false; while(c.p<c.end && std::isdigit((unsigned char)*c.p)) ++c.p; }
 out.assign(start, c.p-start); return true; }
static bool parseValue(JsonCursor& c, std::string& asStr);
static bool parseArray(JsonCursor& c, std::string& out){ const char* start=c.p; if(*c.p!='[') return false; int depth=0; do{ if(*c.p=='[') ++depth; if(*c.p==']') --depth; ++c.p; } while(c.p<c.end && depth>0); if(depth==0){ out.assign(start, c.p-start); return true; } return false; }
static bool parseObjectRaw(JsonCursor& c, std::string& out){ const char* start=c.p; if(*c.p!='{') return false; int depth=0; do{ if(*c.p=='{') ++depth; if(*c.p=='}') --depth; ++c.p; } while(c.p<c.end && depth>0); if(depth==0){ out.assign(start, c.p-start); return true; } return false; }
static bool parseValue(JsonCursor& c, std::string& asStr){ skipWS(c); if(c.p>=c.end) return false; char ch=*c.p; if(ch=='"'){ return parseString(c, asStr); } else if(ch=='{' ){ return parseObjectRaw(c, asStr); } else if(ch=='['){ return parseArray(c, asStr); } else if(std::isdigit((unsigned char)ch) || ch=='-' || ch=='+'){ return parseNumber(c, asStr); } else { if(parseLiteral(c, "true", &asStr)) return true; if(parseLiteral(c, "false", &asStr)) return true; if(parseLiteral(c, "null", &asStr)) return true; }
  return false; }
} // anon

bool parseJsonObjectFlat(const std::string& json,
                         std::unordered_map<std::string,std::string>& out) {
  JsonCursor c{ json.data(), json.data()+json.size() };
  skipWS(c); if (c.p>=c.end || *c.p!='{') return false; ++c.p; skipWS(c);
  while (c.p<c.end && *c.p!='}') {
    std::string key; if(!parseString(c,key)) return false; skipWS(c); if (c.p>=c.end || *c.p!=':') return false; ++c.p; skipWS(c);
    std::string val; if(!parseValue(c,val)) return false; out[key]=val; skipWS(c);
    if (c.p<c.end && *c.p==','){ ++c.p; skipWS(c); continue; }
    if (c.p<c.end && *c.p=='}'){ break; }
  }
  if (c.p>=c.end || *c.p!='}') return false; ++c.p; skipWS(c);
  return true;
}

} // namespace vsm::rest
