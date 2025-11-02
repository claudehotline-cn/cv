#include "storage/source_repo.hpp"

#include <sstream>

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

namespace va::storage {

bool SourceRepo::listPaged(int page,
                           int page_size,
                           std::vector<SourceRow>* out,
                           std::int64_t* total,
                           std::string* err) {
    if (out) out->clear();
    if (total) *total = 0;
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        const int p = (page <= 0) ? 1 : page;
        const int ps = (page_size <= 0 || page_size > 1000) ? 100 : page_size;

        // Count
        {
            std::unique_ptr<sql::PreparedStatement> ps_count(conn->prepareStatement(
                "SELECT COUNT(*) AS c FROM sources"));
            std::unique_ptr<sql::ResultSet> rs(ps_count->executeQuery());
            if (rs->next() && total) *total = rs->getInt64("c");
        }

        // Page
        std::unique_ptr<sql::PreparedStatement> psq(conn->prepareStatement(
            "SELECT id, uri, status, JSON_EXTRACT(caps,'$') AS caps, fps, UNIX_TIMESTAMP(updated_at) AS upd_sec "
            "FROM sources ORDER BY updated_at DESC LIMIT ? OFFSET ?"));
        psq->setInt(1, ps);
        psq->setInt(2, (p - 1) * ps);
        std::unique_ptr<sql::ResultSet> rs(psq->executeQuery());
        while (rs->next()) {
            SourceRow r;
            r.id = rs->getString("id");
            r.uri = rs->getString("uri");
            r.status = rs->getString("status");
            r.caps_json = rs->isNull("caps") ? std::string() : rs->getString("caps");
            r.fps = rs->isNull("fps") ? 0.0 : rs->getDouble("fps");
            const std::int64_t secs = rs->isNull("upd_sec") ? 0 : rs->getInt64("upd_sec");
            r.updated_ms = secs * 1000;
            out->push_back(std::move(r));
        }
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql query error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) {
        if (err) *err = ex.what();
    }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

bool SourceRepo::listTopN(int limit,
                          std::vector<SourceRow>* out,
                          std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        const int lim = (limit <= 0 || limit > 1000) ? 100 : limit;
        std::unique_ptr<sql::PreparedStatement> psq(conn->prepareStatement(
            "SELECT id, uri, status, JSON_EXTRACT(caps,'$') AS caps, fps, UNIX_TIMESTAMP(updated_at) AS upd_sec "
            "FROM sources ORDER BY updated_at DESC LIMIT ?"));
        psq->setInt(1, lim);
        std::unique_ptr<sql::ResultSet> rs(psq->executeQuery());
        while (rs->next()) {
            SourceRow r;
            r.id = rs->getString("id");
            r.uri = rs->getString("uri");
            r.status = rs->getString("status");
            r.caps_json = rs->isNull("caps") ? std::string() : rs->getString("caps");
            r.fps = rs->isNull("fps") ? 0.0 : rs->getDouble("fps");
            const std::int64_t secs = rs->isNull("upd_sec") ? 0 : rs->getInt64("upd_sec");
            r.updated_ms = secs * 1000;
            out->push_back(std::move(r));
        }
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql query error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) {
        if (err) *err = ex.what();
    }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

} // namespace va::storage

