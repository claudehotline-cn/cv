#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"
#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class LogRepo {
public:
    LogRepo(std::shared_ptr<DbPool> pool,
            const AppConfigPayload::DatabaseConfig& cfg)
        : pool_(std::move(pool)), cfg_(cfg) {}

    bool append(const std::vector<LogRow>& rows, std::string* err = nullptr);
    bool listRecent(const std::string& pipeline,
                    const std::string& level,
                    int limit,
                    std::vector<LogRow>* out,
                    std::string* err = nullptr);

    bool listRecentFiltered(const std::string& pipeline,
                            const std::string& level,
                            const std::string& stream_id,
                            const std::string& node,
                            std::uint64_t from_ts_ms,
                            std::uint64_t to_ts_ms,
                            int limit,
                            std::vector<LogRow>* out,
                            std::string* err = nullptr);

    // Paged listing with total count
    bool listRecentFilteredPaged(const std::string& pipeline,
                                 const std::string& level,
                                 const std::string& stream_id,
                                 const std::string& node,
                                 std::uint64_t from_ts_ms,
                                 std::uint64_t to_ts_ms,
                                 int page,
                                 int page_size,
                                 std::vector<LogRow>* out,
                                 std::int64_t* total,
                                 std::string* err = nullptr);

    // Maintenance: delete rows older than given seconds
    bool purgeOlderThanSeconds(std::uint64_t seconds, std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
    AppConfigPayload::DatabaseConfig cfg_;
};

} // namespace va::storage
