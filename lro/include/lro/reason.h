#pragma once
#include <string>

namespace lro {

inline std::string normalizeReason(const std::string& app_err, const std::string& fallback) {
  (void)app_err; return fallback; // placeholder; users may inject custom logic via RunnerConfig
}

} // namespace lro

