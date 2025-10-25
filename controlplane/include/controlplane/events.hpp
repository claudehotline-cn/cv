#pragma once
#include <string>

namespace controlplane::events {

struct PhaseEvent {
  std::string id;
  std::string phase;     // pending/preparing/ready/failed/cancelled...
  long long ts_ms{0};
  std::string reason;    // optional
};

inline std::string json_escape(const std::string& s) {
  std::string out; out.reserve(s.size()+8);
  for (char c : s) {
    switch (c) {
      case '\\': out += "\\\\"; break;
      case '"': out += "\\\""; break;
      case '\n': out += "\\n"; break;
      case '\r': out += "\\r"; break;
      case '\t': out += "\\t"; break;
      default: out.push_back(c); break;
    }
  }
  return out;
}

inline std::string to_json(const PhaseEvent& e) {
  std::string j = "{";
  j += "\"id\":\"" + json_escape(e.id) + "\",";
  j += "\"phase\":\"" + json_escape(e.phase) + "\",";
  j += "\"ts_ms\":" + std::to_string(e.ts_ms);
  if (!e.reason.empty()) {
    j += ",\"reason\":\"" + json_escape(e.reason) + "\"";
  }
  j += "}";
  return j;
}

} // namespace controlplane::events


