#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class EventRepo {
public:
    explicit EventRepo(std::shared_ptr<DbPool> pool) : pool_(std::move(pool)) {}

    // Append events (batch insert). Returns true on success.
    bool append(const std::vector<EventRow>& rows, std::string* err = nullptr);

    // List recent events with optional filters; limit 1..1000 (enforced by caller).
    bool listRecent(const std::string& pipeline,
                    const std::string& level,
                    int limit,
                    std::vector<EventRow>* out,
                    std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
};

} // namespace va::storage

