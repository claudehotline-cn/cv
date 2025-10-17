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
    bool getStats(Stats* out) const override { if (!out) return false; *out = Stats{}; return false; }
};

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
class MySqlDbPool final : public DbPool {
public:
    explicit MySqlDbPool(const AppConfigPayload::DatabaseConfig& cfg) : cfg_(cfg) {
        max_ = cfg.pool.max > 0 ? cfg.pool.max : 16;
        min_ = cfg.pool.min > 0 ? cfg.pool.min : 2;
    }
    bool valid() const override { return true; }
    bool ping(std::string* err) override {
        auto h = acquire(err);
        return static_cast<bool>(h);
    }
    bool getStats(Stats* out) const override {
        if (!out) return false;
        std::unique_lock<std::mutex> lk(mu_);
        out->max = max_;
        out->min = min_;
        out->idle = idle_.size();
        out->created = created_;
        return true;
    }

    std::unique_ptr<sql::Connection, std::function<void(sql::Connection*)>> acquire(std::string* err = nullptr) override {
        std::unique_lock<std::mutex> lk(mu_);
        if (!idle_.empty()) {
            auto* c = idle_.back().release(); idle_.pop_back();
            return makeHandle(c);
        }
        if (created_ < static_cast<size_t>(max_)) {
            lk.unlock(); auto* c = createOne(err); lk.lock();
            if (c) { ++created_; return makeHandle(c); }
            return {nullptr, [](sql::Connection*){}};
        }
        // fallback: create non-pooled temporary connection
        auto* tmp = createOne(err);
        return std::unique_ptr<sql::Connection, std::function<void(sql::Connection*)>>(tmp, [](sql::Connection* p){ try { delete p; } catch(...){} });
    }

private:
    sql::Connection* createOne(std::string* err) {
        try {
            sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();
            if (!driver) { if (err) *err = "mysql driver unavailable"; return nullptr; }
            // Prefer explicit URL to ensure the configured port is honored (e.g., 13306)
            std::ostringstream url; url << "tcp://" << cfg_.host << ":" << cfg_.port;
            sql::Connection* c = nullptr;
            try {
                c = driver->connect(url.str(), cfg_.user, cfg_.password);
            } catch (const sql::SQLException& ex) {
                // Fallback: if driver supports ConnectOptionsMap (for timeouts), try short timeouts
                try {
                    sql::ConnectOptionsMap props;
                    props["hostName"] = cfg_.host;
                    props["port"] = static_cast<int>(cfg_.port);
                    props["userName"] = cfg_.user;
                    props["password"] = cfg_.password;
                    int to_sec = (cfg_.pool.timeout_ms > 0) ? static_cast<int>(cfg_.pool.timeout_ms / 1000) : 2;
                    if (to_sec <= 0) to_sec = 2;
                    props["OPT_CONNECT_TIMEOUT"] = to_sec;
                    props["OPT_READ_TIMEOUT"] = to_sec;
                    props["OPT_WRITE_TIMEOUT"] = to_sec;
                    c = driver->connect(props);
                } catch (...) {
                    throw; // rethrow original
                }
            }
            if (!c) { if (err) *err = "mysql connect returned null"; return nullptr; }
            c->setSchema(cfg_.db);
            std::unique_ptr<sql::Statement> st(c->createStatement());
            (void)st->executeQuery("SELECT 1");
            return c;
        } catch (const sql::SQLException& ex) {
            if (err) { std::ostringstream os; os << "mysql connect error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
        } catch (const std::exception& ex) { if (err) *err = ex.what(); }
        return nullptr;
    }

    std::unique_ptr<sql::Connection, std::function<void(sql::Connection*)>> makeHandle(sql::Connection* c) {
        return {c, [this](sql::Connection* p){
            if (!p) return;
            std::unique_lock<std::mutex> lk(mu_);
            if (idle_.size() < static_cast<size_t>(max_)) idle_.emplace_back(p);
            else { lk.unlock(); try { delete p; } catch(...){} }
        }};
    }

    AppConfigPayload::DatabaseConfig cfg_;
    int max_ {16};
    int min_ {2};
    mutable std::mutex mu_;
    std::vector<std::unique_ptr<sql::Connection>> idle_;
    size_t created_ {0};
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
