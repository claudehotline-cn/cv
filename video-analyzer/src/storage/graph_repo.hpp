#pragma once

#include "storage/db_pool.hpp"
#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

struct GraphRow {
    std::string id;      // graphs.id
    std::string name;    // graphs.name
    std::string requires_json; // JSON string of requires (may be empty)
};

class GraphRepo {
public:
    GraphRepo(std::shared_ptr<DbPool> pool,
              const AppConfigPayload::DatabaseConfig& cfg)
        : pool_(std::move(pool)), cfg_(cfg) {}

    // List all graphs from DB (ordered by name). Returns false on error.
    bool listAll(std::vector<GraphRow>* out, std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
    AppConfigPayload::DatabaseConfig cfg_;
};

} // namespace va::storage

