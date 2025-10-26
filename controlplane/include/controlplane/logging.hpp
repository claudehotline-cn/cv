#pragma once
#include <string>
#include <nlohmann/json.hpp>

namespace controlplane::logging {

// Emit structured audit log to stdout as a single line JSON.
// Required fields: ts_ms, level, event, corr_id; plus any extra key-values from payload.
void audit(const std::string& event,
           const std::string& corr_id,
           const nlohmann::json& payload = {});

}

