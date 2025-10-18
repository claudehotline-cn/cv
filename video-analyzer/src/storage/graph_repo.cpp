#include "storage/graph_repo.hpp"

#include <sstream>

#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
#  include <mysql/jdbc.h>
#endif

namespace va::storage {

bool GraphRepo::listAll(std::vector<GraphRow>* out, std::string* err) {
    if (out) out->clear();
    if (!pool_ || !pool_->valid()) { if (err) *err = "database disabled"; return false; }
#if defined(VA_WITH_MYSQL) && defined(HAVE_MYSQL_JDBC)
    auto conn = pool_->acquire(err);
    if (!conn) return false;
    try {
        std::unique_ptr<sql::PreparedStatement> ps(conn->prepareStatement(
            "SELECT id, name, JSON_EXTRACT(requires,'$') AS req FROM graphs ORDER BY name ASC"));
        std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
        while (rs->next()) {
            GraphRow r;
            r.id = rs->getString("id");
            r.name = rs->isNull("name") ? std::string() : rs->getString("name");
            r.requires_json = rs->isNull("req") ? std::string() : rs->getString("req");
            if (out) out->push_back(std::move(r));
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

