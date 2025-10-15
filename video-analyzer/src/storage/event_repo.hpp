#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"
#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class EventRepo {
public:
    EventRepo(std::shared_ptr<DbPool> pool,
              const AppConfigPayload::DatabaseConfig& cfg)
        : pool_(std::move(pool)), cfg_(cfg) {}

    // Append events (batch insert). Returns true on success.
    bool append(const std::vector<EventRow>& rows, std::string* err = nullptr);

    // List recent events with optional filters; limit 1..1000 (enforced by caller).
    // Extended filters: stream_id, node, from_ts_ms/to_ts_ms (0 to ignore)
    bool listRecent(const std::string& pipeline,
                    const std::string& level,
                    int limit,
                    std::vector<EventRow>* out,
                    std::string* err = nullptr);

    bool listRecentFiltered(const std::string& pipeline,
                            const std::string& level,
                            const std::string& stream_id,
                            const std::string& node,
                            std::uint64_t from_ts_ms,
                            std::uint64_t to_ts_ms,
                            int limit,
                            std::vector<EventRow>* out,
                            std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
    AppConfigPayload::DatabaseConfig cfg_;
};

} // namespace va::storage
