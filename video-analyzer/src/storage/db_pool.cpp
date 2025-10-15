#include "storage/db_pool.hpp"

#include <mutex>

namespace va::storage {

namespace {
class NullDbPool final : public DbPool {
public:
    explicit NullDbPool(const AppConfigPayload::DatabaseConfig&) {}
    bool valid() const override { return false; }
    bool ping(std::string* err) override {
        if (err) *err = "database disabled (VA_WITH_MYSQL=OFF)";
        return false;
    }
};
} // namespace

std::shared_ptr<DbPool> DbPool::create(const AppConfigPayload::DatabaseConfig& cfg) {
#if defined(VA_WITH_MYSQL)
    // Placeholder: real MySQL-backed pool to be implemented when MySQL client is available.
    // For now, return NullDbPool to avoid link-time dependency in default builds.
    return std::make_shared<NullDbPool>(cfg);
#else
    return std::make_shared<NullDbPool>(cfg);
#endif
}

} // namespace va::storage

