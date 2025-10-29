#pragma once
#include <string>
#include <nlohmann/json.hpp>
#include "controlplane/config.hpp"

namespace controlplane::db {

// Return true and fill json_out with array JSON on success; false on error
bool list_models_json(const AppConfig& cfg, std::string* json_out);
bool list_pipelines_json(const AppConfig& cfg, std::string* json_out);
bool list_graphs_json(const AppConfig& cfg, std::string* json_out);

// Return last DB error snapshot (best-effort; cleared on demand)
void db_error_snapshot(nlohmann::json* out);
void db_error_clear();

}
