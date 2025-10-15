#include "storage/event_repo.hpp"

#include <sstream>

// Include MySQL JDBC headers at global scope to avoid namespace pollution
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

namespace va::storage {

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#endif

bool EventRepo::append(const std::vector<EventRow>& rows, std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    if (rows.empty()) return true;
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        const std::size_t chunk = 128;
        for (std::size_t i = 0; i < rows.size(); i += chunk) {
            const std::size_t n = std::min(chunk, rows.size() - i);
            std::ostringstream sql;
            sql << "INSERT INTO events (ts, level, type, pipeline, node, stream_id, msg, extra) VALUES ";
            for (std::size_t k = 0; k < n; ++k) {
                if (k) sql << ',';
                sql << "(FROM_UNIXTIME(?),?,?,?,?,?,?,?)";
            }
            std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
            int idx = 1;
            for (std::size_t k = 0; k < n; ++k) {
                const auto& r = rows[i + k];
                const std::int64_t secs = r.ts_ms > 0 ? (r.ts_ms / 1000) : 0;
                ps->setInt64(idx++, secs);
                ps->setString(idx++, r.level);
                ps->setString(idx++, r.type);
                if (!r.pipeline.empty()) ps->setString(idx++, r.pipeline); else ps->setNull(idx++, 0);
                if (!r.node.empty()) ps->setString(idx++, r.node); else ps->setNull(idx++, 0);
                if (!r.stream_id.empty()) ps->setString(idx++, r.stream_id); else ps->setNull(idx++, 0);
                ps->setString(idx++, r.msg);
                if (!r.extra_json.empty()) ps->setString(idx++, r.extra_json); else ps->setNull(idx++, 0);
            }
            ps->executeUpdate();
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

bool EventRepo::listRecent(const std::string& pipeline, const std::string& level, int limit, std::vector<EventRow>* out, std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::ostringstream sql;
        sql << "SELECT UNIX_TIMESTAMP(ts) AS ts_sec, level, type, pipeline, node, stream_id, msg, JSON_EXTRACT(extra,'$') AS extra FROM events WHERE 1=1 ";
        if (!pipeline.empty()) sql << "AND pipeline=? ";
        if (!level.empty())    sql << "AND level=? ";
        sql << "ORDER BY ts DESC LIMIT ?";
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
        int idx = 1;
        if (!pipeline.empty()) ps->setString(idx++, pipeline);
        if (!level.empty())    ps->setString(idx++, level);
        ps->setInt(idx++, (limit <= 0 || limit > 1000) ? 100 : limit);
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            EventRow r;
            const std::int64_t secs = rs->getInt64("ts_sec");
            r.ts_ms = secs * 1000;
            r.level = rs->getString("level");
            r.type = rs->getString("type");
            r.pipeline = rs->isNull("pipeline") ? std::string() : rs->getString("pipeline");
            r.node = rs->isNull("node") ? std::string() : rs->getString("node");
            r.stream_id = rs->isNull("stream_id") ? std::string() : rs->getString("stream_id");
            r.msg = rs->getString("msg");
            r.extra_json = rs->isNull("extra") ? std::string() : rs->getString("extra");
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

bool EventRepo::purgeOlderThanSeconds(std::uint64_t seconds, std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement("DELETE FROM events WHERE ts < NOW() - INTERVAL ? SECOND"));
        ps->setInt64(1, static_cast<std::int64_t>(seconds));
        ps->executeUpdate();
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql delete error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) {
        if (err) *err = ex.what();
    }
    return false;
#else
    if (err) *err = "not implemented";
    return false;
#endif
}

bool EventRepo::listRecentFiltered(const std::string& pipeline,
                                   const std::string& level,
                                   const std::string& stream_id,
                                   const std::string& node,
                                   std::uint64_t from_ts_ms,
                                   std::uint64_t to_ts_ms,
                                   int limit,
                                   std::vector<EventRow>* out,
                                   std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::ostringstream sql;
        sql << "SELECT UNIX_TIMESTAMP(ts) AS ts_sec, level, type, pipeline, node, stream_id, msg, JSON_EXTRACT(extra,'$') AS extra FROM events WHERE 1=1 ";
        if (!pipeline.empty()) sql << "AND pipeline=? ";
        if (!level.empty())    sql << "AND level=? ";
        if (!stream_id.empty()) sql << "AND stream_id=? ";
        if (!node.empty())      sql << "AND node=? ";
        if (from_ts_ms > 0)     sql << "AND ts >= FROM_UNIXTIME(?) ";
        if (to_ts_ms > 0)       sql << "AND ts <= FROM_UNIXTIME(?) ";
        sql << "ORDER BY ts DESC LIMIT ?";
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
        int idx = 1;
        if (!pipeline.empty())   ps->setString(idx++, pipeline);
        if (!level.empty())      ps->setString(idx++, level);
        if (!stream_id.empty())  ps->setString(idx++, stream_id);
        if (!node.empty())       ps->setString(idx++, node);
        if (from_ts_ms > 0)      ps->setInt64(idx++, static_cast<std::int64_t>(from_ts_ms/1000));
        if (to_ts_ms > 0)        ps->setInt64(idx++, static_cast<std::int64_t>(to_ts_ms/1000));
        ps->setInt(idx++, (limit <= 0 || limit > 1000) ? 100 : limit);
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            EventRow r;
            const std::int64_t secs = rs->getInt64("ts_sec"); r.ts_ms = secs * 1000;
            r.level = rs->getString("level"); r.type = rs->getString("type");
            r.pipeline = rs->isNull("pipeline") ? std::string() : rs->getString("pipeline");
            r.node = rs->isNull("node") ? std::string() : rs->getString("node");
            r.stream_id = rs->isNull("stream_id") ? std::string() : rs->getString("stream_id");
            r.msg = rs->getString("msg");
            r.extra_json = rs->isNull("extra") ? std::string() : rs->getString("extra");
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
