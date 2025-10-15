#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class LogRepo {
public:
    explicit LogRepo(std::shared_ptr<DbPool> pool) : pool_(std::move(pool)) {}

    bool append(const std::vector<LogRow>& rows, std::string* err = nullptr);
    bool listRecent(const std::string& pipeline,
                    const std::string& level,
                    int limit,
                    std::vector<LogRow>* out,
                    std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
};

} // namespace va::storage

