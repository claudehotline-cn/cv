#include "lro/adapters/rest_simple.h"
#include "lro/runner.h"
#include "lro/status.h"
#include <chrono>
#include <sstream>

namespace lro::rest {

static std::string extract_idempotency_key(const std::string& body) {
  // Very loose JSON sniffing: find "idempotency_key":"..."
  const std::string pat = "\"idempotency_key\"\s*:\s*\"";
  auto pos = body.find("\"idempotency_key\"");
  if (pos == std::string::npos) return std::string();
  auto q1 = body.find('"', body.find(':', pos));
  if (q1 == std::string::npos) return std::string();
  auto q2 = body.find('"', q1 + 1);
  if (q2 == std::string::npos) return std::string();
  return body.substr(q1 + 1, q2 - (q1 + 1));
}

static std::string json_escape(const std::string& s) {
  std::ostringstream os; os << '"';
  for (char c : s) {
    if (c == '"' || c == '\\') os << '\\' << c; else if (c=='\n') os << "\\n"; else os << c;
  }
  os << '"';
  return os.str();
}

void register_basic_routes(RouterHooks& hooks, Runner* runner) {
  if (!runner) return;
  // POST /operations
  if (hooks.post) {
    hooks.post("/operations", [runner](const std::string& body) -> std::string {
      std::string key = extract_idempotency_key(body);
      if (key.empty()) key = "demo"; // default demo key
      std::string id = runner->create(body, key);
      std::ostringstream os; os << "{\"id\":" << json_escape(id) << "}"; return os.str();
    });
  }
  // GET /operations
  if (hooks.get) {
    hooks.get("/operations", [runner](const std::string& id) -> std::string {
      auto op = runner->get(id);
      if (!op) return std::string("{\"error\":\"not_found\"}");
      std::ostringstream os;
      os << "{\"id\":" << json_escape(id)
         << ",\"status\":" << json_escape(to_string(op->status.load()))
         << ",\"phase\":" << json_escape(op->phase);
      if (!op->reason.empty()) os << ",\"reason\":" << json_escape(op->reason);
      try {
        auto ms = (long long)std::chrono::duration_cast<std::chrono::milliseconds>(op->created_at.time_since_epoch()).count();
        os << ",\"created_at_ms\":" << ms;
      } catch (...) {}
      os << "}";
      return os.str();
    });
  }
  // DELETE /operations
  if (hooks.del) {
    hooks.del("/operations", [runner](const std::string& id) -> std::string {
      bool ok = runner->cancel(id);
      return ok ? std::string("{\"ok\":true}") : std::string("{\"ok\":false}");
    });
  }
}

} // namespace lro::rest

