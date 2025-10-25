#pragma once
#include <string>
#include "controlplane/http_server.hpp"

namespace controlplane::sse {

inline void write_headers(StreamWriter w) {
  std::string hdr =
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: text/event-stream\r\n"
    "Cache-Control: no-cache\r\n"
    "Connection: keep-alive\r\n"
    "Access-Control-Allow-Origin: *\r\n"
    "Access-Control-Expose-Headers: ETag,Location\r\n\r\n";
  if (w.send) w.send(w.opaque, hdr.c_str(), hdr.size());
}

inline void write_event(StreamWriter w, const std::string& name, const std::string& data_json) {
  std::string ev;
  ev.reserve(name.size() + data_json.size() + 32);
  ev += "event: "; ev += name; ev += "\n";
  ev += "data: "; ev += data_json; ev += "\n\n";
  if (w.send) w.send(w.opaque, ev.c_str(), ev.size());
}

inline void write_comment(StreamWriter w, const std::string& text) {
  std::string c=":"; c += " "; c += text; c += "\n\n";
  if (w.send) w.send(w.opaque, c.c_str(), c.size());
}

inline void close(StreamWriter w) {
  if (w.close) w.close(w.opaque);
}

} // namespace controlplane::sse



