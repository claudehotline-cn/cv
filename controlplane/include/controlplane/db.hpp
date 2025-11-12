#pragma once
#include <string>
#include <nlohmann/json.hpp>
#include "controlplane/config.hpp"

namespace controlplane::db {

// Return true and fill json_out with array JSON on success; false on error
bool list_models_json(const AppConfig& cfg, std::string* json_out);
bool list_pipelines_json(const AppConfig& cfg, std::string* json_out);
bool list_graphs_json(const AppConfig& cfg, std::string* json_out);

// Train jobs CRUD (best-effort; driver dependent). All JSON outputs are compact strings.
// Create or upsert a train job with minimal fields.
bool train_job_create(const AppConfig& cfg,
                      const std::string& id,
                      const std::string& status,
                      const std::string& phase,
                      const nlohmann::json& cfg_json);

// Update arbitrary subset of fields. "fields" may contain keys:
//  status, phase, mlflow_run_id, registered_model, registered_version, metrics, artifacts, error
bool train_job_update(const AppConfig& cfg,
                      const std::string& id,
                      const nlohmann::json& fields);

// Get single job as JSON object; returns false on hard DB error. If not found, returns true with "{}".
bool train_job_get_json(const AppConfig& cfg, const std::string& id, std::string* json_out);

// List jobs as JSON array (ordered by updated_at desc, limit optional in future).
bool list_train_jobs_json(const AppConfig& cfg, std::string* json_out);

// Return last DB error snapshot (best-effort; cleared on demand)
void db_error_snapshot(nlohmann::json* out);
void db_error_clear();

}
