#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"
#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class SessionRepo {
public:
    SessionRepo(std::shared_ptr<DbPool> pool,
                const AppConfigPayload::DatabaseConfig& cfg)
        : pool_(std::move(pool)), cfg_(cfg) {}

    // Create a new session row. Returns inserted id via out_id if provided.
    bool start(const std::string& stream_id,
               const std::string& pipeline,
               const std::string& model_id,
               const std::string& source_uri,
               std::int64_t started_ts_ms,
               std::int64_t* out_id = nullptr,
               std::string* err = nullptr);

    // Mark latest active session (by started_at DESC) as completed.
    bool completeLatest(const std::string& stream_id,
                        const std::string& pipeline,
                        const std::string& status,
                        const std::string& error_msg,
                        std::int64_t stopped_ts_ms,
                        std::string* err = nullptr);

    // List recent sessions with optional filters.
    bool listRecent(const std::string& stream_id,
                    const std::string& pipeline,
                    int limit,
                    std::vector<SessionRow>* out,
                    std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
    AppConfigPayload::DatabaseConfig cfg_;
};

} // namespace va::storage
