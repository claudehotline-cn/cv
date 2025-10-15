#pragma once

#include "ConfigLoader.hpp"

#include <memory>
#include <string>
#include <functional>

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
namespace sql { class Connection; }
#endif

namespace va::storage {

// Minimal database pool interface; concrete impl behind compile flag.
class DbPool {
public:
    virtual ~DbPool() = default;
    virtual bool valid() const = 0;
    virtual bool ping(std::string* err = nullptr) = 0;

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    // Acquire a JDBC connection with RAII deleter that returns it to the pool.
    // When pool is unavailable, returned unique_ptr will be null.
    virtual std::unique_ptr<sql::Connection, std::function<void(sql::Connection*)>> acquire(std::string* /*err*/ = nullptr) { return {nullptr, [](sql::Connection*){}}; }
#endif

    static std::shared_ptr<DbPool> create(const AppConfigPayload::DatabaseConfig& cfg);
};

} // namespace va::storage
