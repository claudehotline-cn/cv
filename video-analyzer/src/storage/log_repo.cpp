#include "storage/log_repo.hpp"

#include <sstream>

// Include MySQL JDBC headers at global scope
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

namespace va::storage {

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#endif

bool LogRepo::append(const std::vector<LogRow>& rows, std::string* err) {
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
            sql << "INSERT INTO logs (ts, level, pipeline, node, stream_id, message, extra) VALUES ";
            for (std::size_t k = 0; k < n; ++k) {
                if (k) sql << ',';
                sql << "(FROM_UNIXTIME(?),?,?,?,?,?,?)";
            }
            std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
            int idx = 1;
            for (std::size_t k = 0; k < n; ++k) {
                const auto& r = rows[i + k];
                const std::int64_t secs = r.ts_ms > 0 ? (r.ts_ms / 1000) : 0;
                ps->setInt64(idx++, secs);
                ps->setString(idx++, r.level);
                if (!r.pipeline.empty()) ps->setString(idx++, r.pipeline); else ps->setNull(idx++, 0);
                if (!r.node.empty())     ps->setString(idx++, r.node); else ps->setNull(idx++, 0);
                if (!r.stream_id.empty())ps->setString(idx++, r.stream_id); else ps->setNull(idx++, 0);
                ps->setString(idx++, r.message);
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

bool LogRepo::listRecent(const std::string& pipeline, const std::string& level, int limit, std::vector<LogRow>* out, std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::ostringstream sql;
        sql << "SELECT UNIX_TIMESTAMP(ts) AS ts_sec, level, pipeline, node, stream_id, message, JSON_EXTRACT(extra,'$') AS extra FROM logs WHERE 1=1 ";
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
            LogRow r;
            const std::int64_t secs = rs->getInt64("ts_sec");
            r.ts_ms = secs * 1000;
            r.level = rs->getString("level");
            r.pipeline = rs->isNull("pipeline") ? std::string() : rs->getString("pipeline");
            r.node = rs->isNull("node") ? std::string() : rs->getString("node");
            r.stream_id = rs->isNull("stream_id") ? std::string() : rs->getString("stream_id");
            r.message = rs->getString("message");
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

bool LogRepo::purgeOlderThanSeconds(std::uint64_t seconds, std::string* err) {
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement("DELETE FROM logs WHERE ts < NOW() - INTERVAL ? SECOND"));
        ps->setInt64(1, static_cast<std::int64_t>(seconds));
        ps->executeUpdate();
        return true;
    } catch (const sql::SQLException& ex) {
        if (err) { std::ostringstream os; os << "mysql delete error (" << ex.getErrorCode() << "): " << ex.what(); *err = os.str(); }
    } catch (const std::exception& ex) { if (err) *err = ex.what(); }
    return false;
#else
    if (err) *err = "not implemented"; return false;
#endif
}

bool LogRepo::listRecentFiltered(const std::string& pipeline,
                                 const std::string& level,
                                 const std::string& stream_id,
                                 const std::string& node,
                                 std::uint64_t from_ts_ms,
                                 std::uint64_t to_ts_ms,
                                 int limit,
                                 std::vector<LogRow>* out,
                                 std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::ostringstream sql;
        sql << "SELECT UNIX_TIMESTAMP(ts) AS ts_sec, level, pipeline, node, stream_id, message, JSON_EXTRACT(extra,'$') AS extra FROM logs WHERE 1=1 ";
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
            LogRow r;
            const std::int64_t secs = rs->getInt64("ts_sec"); r.ts_ms = secs * 1000;
            r.level = rs->getString("level");
            r.pipeline = rs->isNull("pipeline") ? std::string() : rs->getString("pipeline");
            r.node = rs->isNull("node") ? std::string() : rs->getString("node");
            r.stream_id = rs->isNull("stream_id") ? std::string() : rs->getString("stream_id");
            r.message = rs->getString("message");
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

bool LogRepo::listRecentFilteredPaged(const std::string& pipeline,
                                      const std::string& level,
                                      const std::string& stream_id,
                                      const std::string& node,
                                      std::uint64_t from_ts_ms,
                                      std::uint64_t to_ts_ms,
                                      int page,
                                      int page_size,
                                      std::vector<LogRow>* out,
                                      std::int64_t* total,
                                      std::string* err) {
    if (out) out->clear();
    if (total) *total = 0;
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        auto split_csv = [](const std::string& s){ std::vector<std::string> v; std::string cur; for(char c: s){ if(c==','){ if(!cur.empty()) { v.push_back(cur); cur.clear(); } } else { cur.push_back(c); } } if(!cur.empty()) v.push_back(cur); return v; };
        const std::vector<std::string> stream_list = split_csv(stream_id);
        const std::vector<std::string> node_list = split_csv(node);
        // Count
        {
            std::ostringstream sql;
            sql << "SELECT COUNT(*) AS c FROM logs WHERE 1=1 ";
            if (!pipeline.empty()) sql << "AND pipeline=? ";
            if (!level.empty())    sql << "AND level=? ";
            if (!stream_id.empty()) {
                if (stream_list.size() > 1) { sql << "AND stream_id IN ("; for (size_t i=0;i<stream_list.size();++i){ if(i) sql << ','; sql << '?'; } sql << ") "; }
                else { sql << "AND stream_id=? "; }
            }
            if (!node.empty()) {
                if (node_list.size() > 1) { sql << "AND node IN ("; for (size_t i=0;i<node_list.size();++i){ if(i) sql << ','; sql << '?'; } sql << ") "; }
                else { sql << "AND node=? "; }
            }
            if (from_ts_ms > 0)     sql << "AND ts >= FROM_UNIXTIME(?) ";
            if (to_ts_ms > 0)       sql << "AND ts <= FROM_UNIXTIME(?) ";
            std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
            int idx = 1;
            if (!pipeline.empty())   ps->setString(idx++, pipeline);
            if (!level.empty())      ps->setString(idx++, level);
            if (!stream_id.empty()) {
                if (stream_list.size() > 1) { for (const auto& s : stream_list) ps->setString(idx++, s); }
                else { ps->setString(idx++, stream_id); }
            }
            if (!node.empty()) {
                if (node_list.size() > 1) { for (const auto& s : node_list) ps->setString(idx++, s); }
                else { ps->setString(idx++, node); }
            }
            if (from_ts_ms > 0)      ps->setInt64(idx++, static_cast<std::int64_t>(from_ts_ms/1000));
            if (to_ts_ms > 0)        ps->setInt64(idx++, static_cast<std::int64_t>(to_ts_ms/1000));
            std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
            if (rs->next()) { if (total) *total = rs->getInt64("c"); }
        }

        // Page bounds
        if (page < 1) page = 1;
        if (page_size <= 0 || page_size > 1000) page_size = 100;
        std::int64_t offset = static_cast<std::int64_t>((page - 1) * page_size);

        std::ostringstream sql;
        sql << "SELECT UNIX_TIMESTAMP(ts) AS ts_sec, level, pipeline, node, stream_id, message, JSON_EXTRACT(extra,'$') AS extra FROM logs WHERE 1=1 ";
        if (!pipeline.empty()) sql << "AND pipeline=? ";
        if (!level.empty())    sql << "AND level=? ";
        if (!stream_id.empty()) {
            if (stream_list.size() > 1) { sql << "AND stream_id IN ("; for (size_t i=0;i<stream_list.size();++i){ if(i) sql << ','; sql << '?'; } sql << ") "; }
            else { sql << "AND stream_id=? "; }
        }
        if (!node.empty()) {
            if (node_list.size() > 1) { sql << "AND node IN ("; for (size_t i=0;i<node_list.size();++i){ if(i) sql << ','; sql << '?'; } sql << ") "; }
            else { sql << "AND node=? "; }
        }
        if (from_ts_ms > 0)     sql << "AND ts >= FROM_UNIXTIME(?) ";
        if (to_ts_ms > 0)       sql << "AND ts <= FROM_UNIXTIME(?) ";
        sql << "ORDER BY ts DESC LIMIT ? OFFSET ?";
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(sql.str()));
        int idx = 1;
        if (!pipeline.empty())   ps->setString(idx++, pipeline);
        if (!level.empty())      ps->setString(idx++, level);
        if (!stream_id.empty()) {
            if (stream_list.size() > 1) { for (const auto& s : stream_list) ps->setString(idx++, s); }
            else { ps->setString(idx++, stream_id); }
        }
        if (!node.empty()) {
            if (node_list.size() > 1) { for (const auto& s : node_list) ps->setString(idx++, s); }
            else { ps->setString(idx++, node); }
        }
        if (from_ts_ms > 0)      ps->setInt64(idx++, static_cast<std::int64_t>(from_ts_ms/1000));
        if (to_ts_ms > 0)        ps->setInt64(idx++, static_cast<std::int64_t>(to_ts_ms/1000));
        ps->setInt(idx++, page_size);
        ps->setInt64(idx++, offset);
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            LogRow r;
            const std::int64_t secs = rs->getInt64("ts_sec"); r.ts_ms = secs * 1000;
            r.level = rs->getString("level");
            r.pipeline = rs->isNull("pipeline") ? std::string() : rs->getString("pipeline");
            r.node = rs->isNull("node") ? std::string() : rs->getString("node");
            r.stream_id = rs->isNull("stream_id") ? std::string() : rs->getString("stream_id");
            r.message = rs->getString("message");
            r.extra_json = rs->isNull("extra") ? std::string() : rs->getString("extra");
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
