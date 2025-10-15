#include "storage/db_pool.hpp"

#include <mutex>
#include <sstream>

// MySQL legacy JDBC API must be included at global scope (not within namespaces)
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

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

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
class MySqlDbPool final : public DbPool {
public:
    explicit MySqlDbPool(const AppConfigPayload::DatabaseConfig& cfg) : cfg_(cfg) {}
    bool valid() const override { return true; }
    bool ping(std::string* err) override {
        try {
            sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();
            if (!driver) { if (err) *err = "mysql driver unavailable"; return false; }
            std::ostringstream url; url << "tcp://" << cfg_.host << ":" << cfg_.port;
            std::unique_ptr<sql::Connection> c(driver->connect(url.str(), cfg_.user, cfg_.password));
            if (!c) { if (err) *err = "mysql connect returned null"; return false; }
            c->setSchema(cfg_.db);
            std::unique_ptr<sql::Statement> st(c->createStatement());
            std::unique_ptr<sql::ResultSet> rs(st->executeQuery("SELECT 1"));
            (void)rs;
            return true;
        } catch (const sql::SQLException& ex) {
            if (err) { std::ostringstream os; os << "mysql ping error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
            return false;
        } catch (const std::exception& ex) {
            if (err) *err = ex.what();
            return false;
        }
    }
private:
    AppConfigPayload::DatabaseConfig cfg_;
};
#endif
} // namespace

std::shared_ptr<DbPool> DbPool::create(const AppConfigPayload::DatabaseConfig& cfg) {
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    return std::make_shared<MySqlDbPool>(cfg);
#else
    return std::make_shared<NullDbPool>(cfg);
#endif
}

} // namespace va::storage
