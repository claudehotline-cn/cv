#include "controlplane/logging.hpp"
#include <iostream>
#include <chrono>
#include <fstream>
#include <cstdlib>

namespace controlplane::logging {

void audit(const std::string& event,
           const std::string& corr_id,
           const nlohmann::json& payload) {
  using namespace std::chrono;
  nlohmann::json j;
  j["ts_ms"] = duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
  j["level"] = "INFO";
  j["event"] = event;
  if (!corr_id.empty()) j["corr_id"] = corr_id; else j["corr_id"] = nullptr;
  if (!payload.is_null() && !payload.empty()) {
    for (auto it = payload.begin(); it != payload.end(); ++it) j[it.key()] = it.value();
  }
  try {
    std::cout << "[AUDIT] " << j.dump() << std::endl;
    const char* flog = std::getenv("CP_AUDIT_LOG");
    if (flog && *flog) {
      std::ofstream ofs(flog, std::ios::app | std::ios::out);
      if (ofs.is_open()) {
        ofs << j.dump() << "\n";
      }
    }
  } catch (...) {
    // swallow
  }
}

}
