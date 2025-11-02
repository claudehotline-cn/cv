#include "controlplane/db.hpp"
#include <string>
#include <sstream>
#include <mutex>
#include <nlohmann/json.hpp>

#ifdef HAVE_MYSQLX
#  include <mysqlx/xdevapi.h>
#endif
#ifdef _WIN32
#  include <windows.h>
#  include <sqlext.h>
#  include <nlohmann/json.hpp>
#endif
#ifdef HAVE_MYSQL_JDBC
#  include <mysql/jdbc.h>
#  include <nlohmann/json.hpp>
#endif

namespace controlplane::db {

namespace {
  static std::mutex g_err_mu;
  static nlohmann::json g_err; // { jdbc:{...}, odbc:{...}, mysqlx:{...} }
  static void err_put(const std::string& cat, const std::string& key, const nlohmann::json& val) {
    std::lock_guard<std::mutex> lk(g_err_mu);
    if (g_err.find(cat) == g_err.end()) g_err[cat] = nlohmann::json::object();
    g_err[cat][key] = val;
  }
}

void db_error_snapshot(nlohmann::json* out) {
  if (!out) return; std::lock_guard<std::mutex> lk(g_err_mu); *out = g_err;
}
void db_error_clear() {
  std::lock_guard<std::mutex> lk(g_err_mu); g_err = nlohmann::json::object();
}

static inline bool use_mysqlx(const AppConfig& cfg) {
  return !cfg.db.driver.empty() && cfg.db.driver == "mysqlx" && !cfg.db.mysqlx_uri.empty();
}

static inline bool use_odbc_mysql(const AppConfig& cfg) {
  if (cfg.db.driver.empty()) return false;
  std::string d = cfg.db.driver; for (auto& c : d) c = (char)tolower((unsigned char)c);
  return (d == "mysql" || d == "odbc");
}

#ifdef _WIN32
static bool odbc_json_query(const std::string& conn_str, const char* sql, std::string* out_json) {
  SQLHENV henv = SQL_NULL_HENV;
  SQLHDBC hdbc = SQL_NULL_HDBC;
  SQLHSTMT hstmt = SQL_NULL_HSTMT;
  if (SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &henv) != SQL_SUCCESS) return false;
  SQLSetEnvAttr(henv, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
  if (SQLAllocHandle(SQL_HANDLE_DBC, henv, &hdbc) != SQL_SUCCESS) { SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  SQLWCHAR outstr[1024]; SQLSMALLINT outstrlen;
  // Convert conn_str to wide
  std::wstring wcs(conn_str.begin(), conn_str.end());
  auto ret = SQLDriverConnectW(hdbc, NULL, (SQLWCHAR*)wcs.c_str(), SQL_NTS, outstr, 1024, &outstrlen, SQL_DRIVER_NOPROMPT);
  if (!(ret == SQL_SUCCESS || ret == SQL_SUCCESS_WITH_INFO)) {
    err_put("odbc", "connect", { {"ret", (int)ret}, {"conn_str", conn_str} });
    SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  if (SQLAllocHandle(SQL_HANDLE_STMT, hdbc, &hstmt) != SQL_SUCCESS) { SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  std::string json = "[]";
  do {
    if (SQLExecDirectA(hstmt, (SQLCHAR*)sql, SQL_NTS) != SQL_SUCCESS) { err_put("odbc", "exec", { {"sql", sql} }); break; }
    SQLRETURN fr = SQLFetch(hstmt);
    if (fr == SQL_SUCCESS || fr == SQL_SUCCESS_WITH_INFO) {
      SQLCHAR buf[65536]; SQLLEN ind = 0; buf[0]=0;
      auto gr = SQLGetData(hstmt, 1, SQL_C_CHAR, buf, sizeof(buf)-1, &ind);
      if (gr == SQL_SUCCESS || gr == SQL_SUCCESS_WITH_INFO) {
        buf[sizeof(buf)-1]=0; json = (const char*)buf; if (json.empty()) json = "[]";
      }
    }
  } while(0);
  SQLFreeHandle(SQL_HANDLE_STMT, hstmt);
  SQLDisconnect(hdbc);
  SQLFreeHandle(SQL_HANDLE_DBC, hdbc);
  SQLFreeHandle(SQL_HANDLE_ENV, henv);
  if (out_json) *out_json = json; return true;
}

static bool odbc_models_json(const std::string& conn_str, std::string* out_json) {
  SQLHENV henv = SQL_NULL_HENV; SQLHDBC hdbc = SQL_NULL_HDBC; SQLHSTMT hstmt = SQL_NULL_HSTMT;
  if (SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &henv) != SQL_SUCCESS) return false;
  SQLSetEnvAttr(henv, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
  if (SQLAllocHandle(SQL_HANDLE_DBC, henv, &hdbc) != SQL_SUCCESS) { SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  std::wstring wcs(conn_str.begin(), conn_str.end()); SQLWCHAR outstr[1024]; SQLSMALLINT outstrlen;
  auto ret = SQLDriverConnectW(hdbc, NULL, (SQLWCHAR*)wcs.c_str(), SQL_NTS, outstr, 1024, &outstrlen, SQL_DRIVER_NOPROMPT);
  if (!(ret == SQL_SUCCESS || ret == SQL_SUCCESS_WITH_INFO)) { err_put("odbc", "connect_models", { {"ret", (int)ret} }); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  if (SQLAllocHandle(SQL_HANDLE_STMT, hdbc, &hstmt) != SQL_SUCCESS) { SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  nlohmann::json arr = nlohmann::json::array();
  const char* q = "SELECT id, task, family, variant, path FROM models";
  if (SQLExecDirectA(hstmt, (SQLCHAR*)q, SQL_NTS) == SQL_SUCCESS) {
    while (true) {
      SQLRETURN fr = SQLFetch(hstmt); if (!(fr == SQL_SUCCESS || fr == SQL_SUCCESS_WITH_INFO)) break;
      char id[256]={0}, task[64]={0}, family[64]={0}, variant[64]={0}, path[512]={0}; SQLLEN ind;
      SQLGetData(hstmt, 1, SQL_C_CHAR, id, sizeof(id)-1, &ind);
      SQLGetData(hstmt, 2, SQL_C_CHAR, task, sizeof(task)-1, &ind);
      SQLGetData(hstmt, 3, SQL_C_CHAR, family, sizeof(family)-1, &ind);
      SQLGetData(hstmt, 4, SQL_C_CHAR, variant, sizeof(variant)-1, &ind);
      SQLGetData(hstmt, 5, SQL_C_CHAR, path, sizeof(path)-1, &ind);
      nlohmann::json o;
      o["id"]=id; if(task[0]) o["task"]=task; if(family[0]) o["family"]=family; if(variant[0]) o["variant"]=variant; if(path[0]) o["path"]=path;
      arr.push_back(o);
    }
  } else { err_put("odbc", "exec_models", { {"sql", q} }); }
  SQLFreeHandle(SQL_HANDLE_STMT, hstmt); SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv);
  if (out_json) *out_json = arr.dump(); return true;
}

static bool odbc_pipelines_json(const std::string& conn_str, std::string* out_json) {
  SQLHENV henv = SQL_NULL_HENV; SQLHDBC hdbc = SQL_NULL_HDBC; SQLHSTMT hstmt = SQL_NULL_HSTMT;
  if (SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &henv) != SQL_SUCCESS) return false;
  SQLSetEnvAttr(henv, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
  if (SQLAllocHandle(SQL_HANDLE_DBC, henv, &hdbc) != SQL_SUCCESS) { SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  std::wstring wcs(conn_str.begin(), conn_str.end()); SQLWCHAR outstr[1024]; SQLSMALLINT outstrlen;
  auto ret = SQLDriverConnectW(hdbc, NULL, (SQLWCHAR*)wcs.c_str(), SQL_NTS, outstr, 1024, &outstrlen, SQL_DRIVER_NOPROMPT);
  if (!(ret == SQL_SUCCESS || ret == SQL_SUCCESS_WITH_INFO)) { err_put("odbc", "connect_pipelines", { {"ret", (int)ret} }); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  if (SQLAllocHandle(SQL_HANDLE_STMT, hdbc, &hstmt) != SQL_SUCCESS) { SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  nlohmann::json arr = nlohmann::json::array();
  const char* q = "SELECT name, graph_id, default_model_id, encoder_cfg FROM pipelines";
  if (SQLExecDirectA(hstmt, (SQLCHAR*)q, SQL_NTS) == SQL_SUCCESS) {
    while (true) {
      SQLRETURN fr = SQLFetch(hstmt); if (!(fr == SQL_SUCCESS || fr == SQL_SUCCESS_WITH_INFO)) break;
      char name[128]={0}, graph_id[128]={0}, default_model_id[256]={0}; SQLLEN ind;
      char encoder_cfg[4096]={0};
      SQLGetData(hstmt, 1, SQL_C_CHAR, name, sizeof(name)-1, &ind);
      SQLGetData(hstmt, 2, SQL_C_CHAR, graph_id, sizeof(graph_id)-1, &ind);
      SQLGetData(hstmt, 3, SQL_C_CHAR, default_model_id, sizeof(default_model_id)-1, &ind);
      SQLGetData(hstmt, 4, SQL_C_CHAR, encoder_cfg, sizeof(encoder_cfg)-1, &ind);
      nlohmann::json o; o["name"]=name; if(graph_id[0]) o["graph_id"]=graph_id; if(default_model_id[0]) o["default_model_id"]=default_model_id;
      // Try parse JSON for encoder_cfg
      try { if(encoder_cfg[0]) o["encoder_cfg"] = nlohmann::json::parse(encoder_cfg); } catch (...) {}
      arr.push_back(o);
    }
  } else { err_put("odbc", "exec_pipelines", { {"sql", q} }); }
  SQLFreeHandle(SQL_HANDLE_STMT, hstmt); SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv);
  if (out_json) *out_json = arr.dump(); return true;
}

static bool odbc_graphs_json(const std::string& conn_str, std::string* out_json) {
  SQLHENV henv = SQL_NULL_HENV; SQLHDBC hdbc = SQL_NULL_HDBC; SQLHSTMT hstmt = SQL_NULL_HSTMT;
  if (SQLAllocHandle(SQL_HANDLE_ENV, SQL_NULL_HANDLE, &henv) != SQL_SUCCESS) return false;
  SQLSetEnvAttr(henv, SQL_ATTR_ODBC_VERSION, (SQLPOINTER)SQL_OV_ODBC3, 0);
  if (SQLAllocHandle(SQL_HANDLE_DBC, henv, &hdbc) != SQL_SUCCESS) { SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  std::wstring wcs(conn_str.begin(), conn_str.end()); SQLWCHAR outstr[1024]; SQLSMALLINT outstrlen;
  auto ret = SQLDriverConnectW(hdbc, NULL, (SQLWCHAR*)wcs.c_str(), SQL_NTS, outstr, 1024, &outstrlen, SQL_DRIVER_NOPROMPT);
  if (!(ret == SQL_SUCCESS || ret == SQL_SUCCESS_WITH_INFO)) { err_put("odbc", "connect_graphs", { {"ret", (int)ret} }); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  if (SQLAllocHandle(SQL_HANDLE_STMT, hdbc, &hstmt) != SQL_SUCCESS) { SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv); return false; }
  nlohmann::json arr = nlohmann::json::array();
  const char* q = "SELECT id, name, requires, file_path FROM graphs";
  if (SQLExecDirectA(hstmt, (SQLCHAR*)q, SQL_NTS) == SQL_SUCCESS) {
    while (true) {
      SQLRETURN fr = SQLFetch(hstmt); if (!(fr == SQL_SUCCESS || fr == SQL_SUCCESS_WITH_INFO)) break;
      char id[128]={0}, name[256]={0}, file_path[512]={0}; SQLLEN ind; char requires[4096]={0};
      SQLGetData(hstmt, 1, SQL_C_CHAR, id, sizeof(id)-1, &ind);
      SQLGetData(hstmt, 2, SQL_C_CHAR, name, sizeof(name)-1, &ind);
      SQLGetData(hstmt, 3, SQL_C_CHAR, requires, sizeof(requires)-1, &ind);
      SQLGetData(hstmt, 4, SQL_C_CHAR, file_path, sizeof(file_path)-1, &ind);
      nlohmann::json o; o["id"]=id; if(name[0]) o["name"]=name; if(file_path[0]) o["file_path"]=file_path;
      try { if(requires[0]) o["requires"] = nlohmann::json::parse(requires); } catch (...) {}
      arr.push_back(o);
    }
  } else { err_put("odbc", "exec_graphs", { {"sql", q} }); }
  SQLFreeHandle(SQL_HANDLE_STMT, hstmt); SQLDisconnect(hdbc); SQLFreeHandle(SQL_HANDLE_DBC, hdbc); SQLFreeHandle(SQL_HANDLE_ENV, henv);
  if (out_json) *out_json = arr.dump(); return true;
}
#endif
#ifdef HAVE_MYSQLX
static bool sql_json_array(mysqlx::Session& sess, const std::string& sql, std::string* out_json) {
  try {
    auto res = sess.sql(sql).execute();
    auto row = res.fetchOne();
    if (!row) { *out_json = "[]"; return true; }
    // first column named `data` contains JSON string
    auto v = row[0];
    // mysqlx::string -> std::string
    *out_json = std::string(v.get<mysqlx::string>());
    if (out_json->empty()) *out_json = "[]";
    return true;
  } catch (const std::exception& ex) {
    err_put("mysqlx", "sql_json_array", { {"msg", ex.what()} });
    return false;
  }
}
#endif

#ifdef HAVE_MYSQL_JDBC
static bool jdbc_models_json(const AppConfig& cfg, std::string* out_json) {
  try {
    sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();
    std::unique_ptr<sql::Connection> con;
    try {
      std::ostringstream url; url << "tcp://" << cfg.db.host << ":" << cfg.db.port;
      con.reset(driver->connect(url.str(), cfg.db.user, cfg.db.password));
    } catch (const sql::SQLException& ex) {
      err_put("jdbc", "connect_url", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} });
      sql::ConnectOptionsMap props;
      props["hostName"] = cfg.db.host; props["port"] = (int)cfg.db.port; props["userName"] = cfg.db.user; props["password"] = cfg.db.password;
      props["CLIENT_SSL"] = false; props["OPT_RECONNECT"] = true; props["OPT_GET_SERVER_PUBLIC_KEY"] = true;
      props["OPT_CONNECT_TIMEOUT"] = 2; props["OPT_READ_TIMEOUT"] = 2; props["OPT_WRITE_TIMEOUT"] = 2;
      try { con.reset(driver->connect(props)); }
      catch (const sql::SQLException& ex2) { err_put("jdbc", "connect_props", { {"code", ex2.getErrorCode()}, {"state", ex2.getSQLState()}, {"msg", ex2.what()} }); throw; }
    }
    con->setSchema(cfg.db.schema);
    std::unique_ptr<sql::Statement> stmt(con->createStatement());
    std::unique_ptr<sql::ResultSet> rs(stmt->executeQuery("SELECT id, task, family, variant, path FROM models"));
    nlohmann::json arr = nlohmann::json::array();
    while (rs->next()) {
      nlohmann::json o;
      o["id"] = rs->getString(1);
      { std::string v = rs->getString(2); if(!v.empty()) o["task"]=v; }
      { std::string v = rs->getString(3); if(!v.empty()) o["family"]=v; }
      { std::string v = rs->getString(4); if(!v.empty()) o["variant"]=v; }
      { std::string v = rs->getString(5); if(!v.empty()) o["path"]=v; }
      arr.push_back(o);
    }
    if (out_json) *out_json = arr.dump();
    return true;
  } catch (const sql::SQLException& ex) { err_put("jdbc", "models", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; } catch (const std::exception& ex) { err_put("jdbc", "models", { {"msg", ex.what()} }); return false; }
}
static bool jdbc_pipelines_json(const AppConfig& cfg, std::string* out_json) {
  try {
    sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();
    std::unique_ptr<sql::Connection> con;
    try {
      std::ostringstream url; url << "tcp://" << cfg.db.host << ":" << cfg.db.port;
      con.reset(driver->connect(url.str(), cfg.db.user, cfg.db.password));
    } catch (const sql::SQLException& ex) {
      err_put("jdbc", "connect_url", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} });
      sql::ConnectOptionsMap props;
      props["hostName"] = cfg.db.host; props["port"] = (int)cfg.db.port; props["userName"] = cfg.db.user; props["password"] = cfg.db.password;
      props["CLIENT_SSL"] = false; props["OPT_RECONNECT"] = true; props["OPT_GET_SERVER_PUBLIC_KEY"] = true;
      props["OPT_CONNECT_TIMEOUT"] = 2; props["OPT_READ_TIMEOUT"] = 2; props["OPT_WRITE_TIMEOUT"] = 2;
      try { con.reset(driver->connect(props)); } catch (const sql::SQLException& ex2) { err_put("jdbc", "connect_props", { {"code", ex2.getErrorCode()}, {"state", ex2.getSQLState()}, {"msg", ex2.what()} }); throw; }
    }
    con->setSchema(cfg.db.schema);
    std::unique_ptr<sql::Statement> stmt(con->createStatement());
    std::unique_ptr<sql::ResultSet> rs(stmt->executeQuery("SELECT name, graph_id, default_model_id, encoder_cfg FROM pipelines"));
    nlohmann::json arr = nlohmann::json::array();
    while (rs->next()) {
      nlohmann::json o;
      o["name"] = rs->getString(1);
      { std::string v = rs->getString(2); if(!v.empty()) o["graph_id"]=v; }
      { std::string v = rs->getString(3); if(!v.empty()) o["default_model_id"]=v; }
      { std::string v = rs->getString(4); if(!v.empty()) { try { o["encoder_cfg"] = nlohmann::json::parse(v); } catch (...) {} } }
      arr.push_back(o);
    }
    if (out_json) *out_json = arr.dump();
    return true;
  } catch (const sql::SQLException& ex) { err_put("jdbc", "pipelines", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; } catch (const std::exception& ex) { err_put("jdbc", "pipelines", { {"msg", ex.what()} }); return false; }
}
static bool jdbc_graphs_json(const AppConfig& cfg, std::string* out_json) {
  try {
    sql::mysql::MySQL_Driver* driver = sql::mysql::get_mysql_driver_instance();
    std::unique_ptr<sql::Connection> con;
    try {
      std::ostringstream url; url << "tcp://" << cfg.db.host << ":" << cfg.db.port;
      con.reset(driver->connect(url.str(), cfg.db.user, cfg.db.password));
    } catch (const sql::SQLException& ex) {
      err_put("jdbc", "connect_url", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} });
      sql::ConnectOptionsMap props;
      props["hostName"] = cfg.db.host; props["port"] = (int)cfg.db.port; props["userName"] = cfg.db.user; props["password"] = cfg.db.password;
      props["CLIENT_SSL"] = false; props["OPT_RECONNECT"] = true; props["OPT_GET_SERVER_PUBLIC_KEY"] = true;
      props["OPT_CONNECT_TIMEOUT"] = 2; props["OPT_READ_TIMEOUT"] = 2; props["OPT_WRITE_TIMEOUT"] = 2;
      try { con.reset(driver->connect(props)); } catch (const sql::SQLException& ex2) { err_put("jdbc", "connect_props", { {"code", ex2.getErrorCode()}, {"state", ex2.getSQLState()}, {"msg", ex2.what()} }); throw; }
    }
    con->setSchema(cfg.db.schema);
    std::unique_ptr<sql::Statement> stmt(con->createStatement());
    std::unique_ptr<sql::ResultSet> rs(stmt->executeQuery("SELECT id, name, requires, file_path FROM graphs"));
    nlohmann::json arr = nlohmann::json::array();
    while (rs->next()) {
      nlohmann::json o;
      o["id"] = rs->getString(1);
      { std::string v = rs->getString(2); if(!v.empty()) o["name"]=v; }
      { std::string v = rs->getString(3); if(!v.empty()) { try { o["requires"] = nlohmann::json::parse(v); } catch (...) {} } }
      { std::string v = rs->getString(4); if(!v.empty()) o["file_path"]=v; }
      arr.push_back(o);
    }
    if (out_json) *out_json = arr.dump();
    return true;
  } catch (const sql::SQLException& ex) { err_put("jdbc", "graphs", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; } catch (const std::exception& ex) { err_put("jdbc", "graphs", { {"msg", ex.what()} }); return false; }
}
#endif

bool list_models_json(const AppConfig& cfg, std::string* json_out) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) { if (jdbc_models_json(cfg, json_out)) return true; }
#endif
#ifdef _WIN32
  if (use_odbc_mysql(cfg) && !cfg.db.host.empty() && cfg.db.port>0 && !cfg.db.user.empty() && !cfg.db.schema.empty()) {
    auto try_odbc = [&](const std::string& drv)->bool{
      std::ostringstream cs; cs << "DRIVER={" << drv << "};SERVER=" << cfg.db.host
        << ";PORT=" << cfg.db.port << ";UID=" << cfg.db.user << ";PWD=" << cfg.db.password
        << ";DATABASE=" << cfg.db.schema << ";OPTION=3;";
      return odbc_models_json(cs.str(), json_out);
    };
    if (!cfg.db.odbc_driver.empty()) { if (try_odbc(cfg.db.odbc_driver)) return true; }
    const char* names[] = {"MySQL ODBC 8.4 Unicode Driver","MySQL ODBC 8.4 ANSI Driver","MySQL ODBC 8.0 Unicode Driver","MySQL ODBC 8.0 ANSI Driver","MariaDB ODBC 3.1 Driver"};
    for (auto n : names) { if (try_odbc(n)) return true; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      // JSON array of objects with key fields
      const char* q =
        "SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT("
        "'id', id, 'task', task, 'family', family, 'variant', variant, 'path', path"
        ")), JSON_ARRAY()) AS data FROM models";
      if (sql_json_array(sess, q, json_out)) return true;
    } catch (...) {}
  }
#endif
  // fallback
  if (json_out) *json_out = "[]"; return true;
}

bool list_pipelines_json(const AppConfig& cfg, std::string* json_out) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) { if (jdbc_pipelines_json(cfg, json_out)) return true; }
#endif
#ifdef _WIN32
  if (use_odbc_mysql(cfg) && !cfg.db.host.empty() && cfg.db.port>0 && !cfg.db.user.empty() && !cfg.db.schema.empty()) {
    auto try_odbc = [&](const std::string& drv)->bool{
      std::ostringstream cs; cs << "DRIVER={" << drv << "};SERVER=" << cfg.db.host
        << ";PORT=" << cfg.db.port << ";UID=" << cfg.db.user << ";PWD=" << cfg.db.password
        << ";DATABASE=" << cfg.db.schema << ";OPTION=3;";
      return odbc_pipelines_json(cs.str(), json_out);
    };
    if (!cfg.db.odbc_driver.empty()) { if (try_odbc(cfg.db.odbc_driver)) return true; }
    const char* names[] = {"MySQL ODBC 8.4 Unicode Driver","MySQL ODBC 8.4 ANSI Driver","MySQL ODBC 8.0 Unicode Driver","MySQL ODBC 8.0 ANSI Driver","MariaDB ODBC 3.1 Driver"};
    for (auto n : names) { if (try_odbc(n)) return true; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      const char* q =
        "SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT("
        "'name', name, 'graph_id', graph_id, 'default_model_id', default_model_id, 'encoder_cfg', encoder_cfg"
        ")), JSON_ARRAY()) AS data FROM pipelines";
      if (sql_json_array(sess, q, json_out)) return true;
    } catch (...) {}
  }
#endif
  if (json_out) *json_out = "[]"; return true;
}

bool list_graphs_json(const AppConfig& cfg, std::string* json_out) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) { if (jdbc_graphs_json(cfg, json_out)) return true; }
#endif
#ifdef _WIN32
  if (use_odbc_mysql(cfg) && !cfg.db.host.empty() && cfg.db.port>0 && !cfg.db.user.empty() && !cfg.db.schema.empty()) {
    auto try_odbc = [&](const std::string& drv)->bool{
      std::ostringstream cs; cs << "DRIVER={" << drv << "};SERVER=" << cfg.db.host
        << ";PORT=" << cfg.db.port << ";UID=" << cfg.db.user << ";PWD=" << cfg.db.password
        << ";DATABASE=" << cfg.db.schema << ";OPTION=3;";
      return odbc_graphs_json(cs.str(), json_out);
    };
    if (!cfg.db.odbc_driver.empty()) { if (try_odbc(cfg.db.odbc_driver)) return true; }
    const char* names[] = {"MySQL ODBC 8.4 Unicode Driver","MySQL ODBC 8.4 ANSI Driver","MySQL ODBC 8.0 Unicode Driver","MySQL ODBC 8.0 ANSI Driver","MariaDB ODBC 3.1 Driver"};
    for (auto n : names) { if (try_odbc(n)) return true; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      const char* q =
        "SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT("
        "'id', id, 'name', name, 'requires', requires, 'file_path', file_path"
        ")), JSON_ARRAY()) AS data FROM graphs";
      if (sql_json_array(sess, q, json_out)) return true;
    } catch (...) {}
  }
#endif
  if (json_out) *json_out = "[]"; return true;
}

} // namespace controlplane::db
