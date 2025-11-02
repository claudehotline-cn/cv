#pragma once

#include "storage/db_pool.hpp"
#include "storage/db_records.hpp"
#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::storage {

class SourceRepo {
public:
    SourceRepo(std::shared_ptr<DbPool> pool,
               const AppConfigPayload::DatabaseConfig& cfg)
        : pool_(std::move(pool)), cfg_(cfg) {}

    // List sources ordered by updated_at desc with pagination
    bool listPaged(int page,
                   int page_size,
                   std::vector<SourceRow>* out,
                   std::int64_t* total,
                   std::string* err = nullptr);

    // Convenience: list first N
    bool listTopN(int limit,
                  std::vector<SourceRow>* out,
                  std::string* err = nullptr);

private:
    std::shared_ptr<DbPool> pool_;
    AppConfigPayload::DatabaseConfig cfg_;
};

} // namespace va::storage

