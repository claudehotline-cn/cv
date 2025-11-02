#include "storage/session_repo.hpp"

#include <sstream>

// Include MySQL JDBC headers at global scope
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

namespace va::storage {

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#endif

bool SessionRepo::start(const std::string& stream_id,
                        const std::string& pipeline,
                        const std::string& model_id,
                        const std::string& source_uri,
                        std::int64_t started_ts_ms,
                        std::int64_t* out_id,
                        std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        // Ensure foreign keys (best-effort)
        if (!stream_id.empty() && !source_uri.empty()) {
            try {
            std::unique_ptr<sql::PreparedStatement> ps0(conn->prepareStatement(
                    "INSERT INTO sources (id, uri, status, created_at, updated_at) VALUES (?,?, 'Unknown', NOW(), NOW()) "
                    "ON DUPLICATE KEY UPDATE uri=VALUES(uri), updated_at=NOW()"));
                ps0->setString(1, stream_id);
                ps0->setString(2, source_uri);
                ps0->executeUpdate();
            } catch (...) { /* ignore */ }
        }
        if (!pipeline.empty()) {
            try {
                std::unique_ptr<sql::PreparedStatement> ps1(conn->prepareStatement(
                    "INSERT IGNORE INTO pipelines (name, created_at, updated_at) VALUES (?, NOW(), NOW())"));
                ps1->setString(1, pipeline);
                ps1->executeUpdate();
            } catch (...) { /* ignore */ }
        }

        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(
            "INSERT INTO sessions (stream_id, pipeline, model_id, status, error_msg, started_at) VALUES (?,?,?,?,?,FROM_UNIXTIME(?))"));
        ps->setString(1, stream_id);
        ps->setString(2, pipeline);
        if (!model_id.empty()) ps->setString(3, model_id); else ps->setNull(3, 0);
        ps->setString(4, "Running");
        ps->setNull(5, 0);
        const std::int64_t secs = started_ts_ms > 0 ? (started_ts_ms / 1000) : 0;
        ps->setInt64(6, secs);
        ps->executeUpdate();
        if (out_id) {
            std::unique_ptr<sql::Statement> st(conn->createStatement());
            std::unique_ptr<sql::ResultSet> rs(st->executeQuery("SELECT LAST_INSERT_ID()"));
            if (rs && rs->next()) { *out_id = rs->getInt64(1); }
        }
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql insert error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) {
        if (err) *err = ex.what();
    }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

bool SessionRepo::completeLatest(const std::string& stream_id,
                                 const std::string& pipeline,
                                 const std::string& status,
                                 const std::string& error_msg,
                                 std::int64_t stopped_ts_ms,
                                 std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(
            "UPDATE sessions SET status=?, error_msg=?, stopped_at=FROM_UNIXTIME(?) "
            "WHERE stream_id=? AND pipeline=? AND stopped_at IS NULL ORDER BY started_at DESC, id DESC LIMIT 1"));
        ps->setString(1, status);
        if (!error_msg.empty()) ps->setString(2, error_msg); else ps->setNull(2, 0);
        const std::int64_t secs = stopped_ts_ms > 0 ? (stopped_ts_ms / 1000) : 0;
        ps->setInt64(3, secs);
        ps->setString(4, stream_id);
        ps->setString(5, pipeline);
        ps->executeUpdate();
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql update error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) {
        if (err) *err = ex.what();
    }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

bool SessionRepo::listRecent(const std::string& stream_id,
                             const std::string& pipeline,
                             int limit,
                             std::vector<SessionRow>* out,
                             std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::ostringstream sql;
        sql << "SELECT id, stream_id, pipeline, model_id, status, error_msg, "
               "UNIX_TIMESTAMP(started_at) AS started_sec, UNIX_TIMESTAMP(stopped_at) AS stopped_sec "
               "FROM sessions WHERE 1=1 ";
        if (!stream_id.empty()) sql << "AND stream_id=? ";
        if (!pipeline.empty())  sql << "AND pipeline=? ";
        sql << "ORDER BY started_at DESC, id DESC LIMIT ?";
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
        int idx = 1;
        if (!stream_id.empty()) ps->setString(idx++, stream_id);
        if (!pipeline.empty())  ps->setString(idx++, pipeline);
        ps->setInt(idx++, (limit <= 0 || limit > 1000) ? 100 : limit);
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            SessionRow r;
            r.id = rs->getInt64("id");
            r.stream_id = rs->getString("stream_id");
            r.pipeline = rs->getString("pipeline");
            r.model_id = rs->isNull("model_id") ? std::string() : rs->getString("model_id");
            r.status = rs->getString("status");
            r.error_msg = rs->isNull("error_msg") ? std::string() : rs->getString("error_msg");
            r.started_ms = rs->getInt64("started_sec") * 1000;
            r.stopped_ms = rs->isNull("stopped_sec") ? 0 : (rs->getInt64("stopped_sec") * 1000);
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

bool SessionRepo::listRangePaginated(const std::string& stream_id,
                                     const std::string& pipeline,
                                     std::uint64_t from_ts_ms,
                                     std::uint64_t to_ts_ms,
                                     int page,
                                     int page_size,
                                     std::vector<SessionRow>* out,
                                     std::uint64_t* total,
                                     std::string* err) {
    if (out) out->clear();
    if (total) *total = 0;
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        if (page <= 0) page = 1;
        if (page_size <= 0 || page_size > 1000) page_size = 50;
        const int offset = (page - 1) * page_size;

        // 1) Count total with filters
        {
            std::ostringstream sqlc;
            sqlc << "SELECT COUNT(*) AS cnt FROM sessions WHERE 1=1 ";
            if (!stream_id.empty()) sqlc << "AND stream_id=? ";
            if (!pipeline.empty())  sqlc << "AND pipeline=? ";
            if (from_ts_ms > 0)     sqlc << "AND started_at >= FROM_UNIXTIME(?) ";
            if (to_ts_ms > 0)       sqlc << "AND started_at <= FROM_UNIXTIME(?) ";
            std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sqlc.str()));
            int idx = 1;
            if (!stream_id.empty()) ps->setString(idx++, stream_id);
            if (!pipeline.empty())  ps->setString(idx++, pipeline);
            if (from_ts_ms > 0)     ps->setInt64(idx++, static_cast<std::int64_t>(from_ts_ms/1000));
            if (to_ts_ms > 0)       ps->setInt64(idx++, static_cast<std::int64_t>(to_ts_ms/1000));
            std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
            if (rs && rs->next()) {
                if (total) *total = static_cast<std::uint64_t>(rs->getInt64("cnt"));
            }
        }

        // 2) Page query
        std::ostringstream sql;
        sql << "SELECT id, stream_id, pipeline, model_id, status, error_msg, "
               "UNIX_TIMESTAMP(started_at) AS started_sec, UNIX_TIMESTAMP(stopped_at) AS stopped_sec "
               "FROM sessions WHERE 1=1 ";
        if (!stream_id.empty()) sql << "AND stream_id=? ";
        if (!pipeline.empty())  sql << "AND pipeline=? ";
        if (from_ts_ms > 0)     sql << "AND started_at >= FROM_UNIXTIME(?) ";
        if (to_ts_ms > 0)       sql << "AND started_at <= FROM_UNIXTIME(?) ";
        sql << "ORDER BY started_at DESC, id DESC LIMIT ? OFFSET ?";
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
        int idx = 1;
        if (!stream_id.empty()) ps->setString(idx++, stream_id);
        if (!pipeline.empty())  ps->setString(idx++, pipeline);
        if (from_ts_ms > 0)     ps->setInt64(idx++, static_cast<std::int64_t>(from_ts_ms/1000));
        if (to_ts_ms > 0)       ps->setInt64(idx++, static_cast<std::int64_t>(to_ts_ms/1000));
        ps->setInt(idx++, page_size);
        ps->setInt(idx++, offset);
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            SessionRow r;
            r.id = rs->getInt64("id");
            r.stream_id = rs->getString("stream_id");
            r.pipeline = rs->getString("pipeline");
            r.model_id = rs->isNull("model_id") ? std::string() : rs->getString("model_id");
            r.status = rs->getString("status");
            r.error_msg = rs->isNull("error_msg") ? std::string() : rs->getString("error_msg");
            r.started_ms = rs->getInt64("started_sec") * 1000;
            r.stopped_ms = rs->isNull("stopped_sec") ? 0 : (rs->getInt64("stopped_sec") * 1000);
            out->push_back(std::move(r));
        }
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql query error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) { if (err) *err = ex.what(); }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

} // namespace va::storage
