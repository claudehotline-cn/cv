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
// 兼容 MySQL Connector/C++ 不同版本的头文件布局：
// - 新版（8.x）通常提供 <mysql/jdbc.h>
// - Ubuntu 自带的 1.1 版仅提供 mysql_connection.h/mysql_driver.h + <cppconn/...>
#  if __has_include(<mysql/jdbc.h>)
#    include <mysql/jdbc.h>
#  else
#    include <mysql_connection.h>
#    include <mysql_driver.h>
#    include <cppconn/statement.h>
#    include <cppconn/resultset.h>
#    include <cppconn/prepared_statement.h>
#  endif
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

// -------------------- train_jobs (CRUD) --------------------

#ifdef HAVE_MYSQL_JDBC
static std::unique_ptr<sql::Connection> jdbc_connect_train(const AppConfig& cfg) {
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
  return con;
}
#endif

bool train_job_create(const AppConfig& cfg,
                      const std::string& id,
                      const std::string& status,
                      const std::string& phase,
                      const nlohmann::json& cfg_json) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) {
    try {
      auto con = jdbc_connect_train(cfg);
      std::unique_ptr<sql::PreparedStatement> ps(con->prepareStatement(
        "INSERT INTO train_jobs(id,status,phase,cfg) VALUES (?,?,?,?) "
        "ON DUPLICATE KEY UPDATE status=VALUES(status), phase=VALUES(phase), cfg=VALUES(cfg), updated_at=CURRENT_TIMESTAMP"));
      ps->setString(1, id);
      ps->setString(2, status);
      ps->setString(3, phase);
      std::string cfgs = cfg_json.dump(); ps->setString(4, cfgs);
      ps->execute();
      return true;
    } catch (const sql::SQLException& ex) { err_put("jdbc", "train_create", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; }
      catch (const std::exception& ex) { err_put("jdbc", "train_create", { {"msg", ex.what()} }); return false; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      auto stmt = sess.sql("INSERT INTO train_jobs(id,status,phase,cfg) VALUES(:id,:s,:p,:cfg) "
                          "ON DUPLICATE KEY UPDATE status=VALUES(status), phase=VALUES(phase), cfg=VALUES(cfg), updated_at=CURRENT_TIMESTAMP");
      stmt.bind("id", id).bind("s", status).bind("p", phase).bind("cfg", cfg_json.dump()).execute();
      return true;
    } catch (const std::exception& ex) { err_put("mysqlx", "train_create", { {"msg", ex.what()} }); return false; }
  }
#endif
  return false; // DB disabled
}

bool train_job_update(const AppConfig& cfg,
                      const std::string& id,
                      const nlohmann::json& fields) {
  if (id.empty()) return false;
  if (!fields.is_object() || fields.empty()) return true; // nothing to do
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) {
    try {
      auto con = jdbc_connect_train(cfg);
      std::ostringstream sql; sql << "UPDATE train_jobs SET ";
      std::vector<std::string> cols;
      bool has_reg_ver=false; int reg_ver=0;
      if (fields.contains("status")) cols.push_back("status=?");
      if (fields.contains("phase")) cols.push_back("phase=?");
      if (fields.contains("mlflow_run_id")) cols.push_back("mlflow_run_id=?");
      if (fields.contains("registered_model")) cols.push_back("registered_model=?");
      if (fields.contains("registered_version")) { cols.push_back("registered_version=?"); has_reg_ver=true; reg_ver = fields["registered_version"].is_number()? fields["registered_version"].get<int>() : 0; }
      if (fields.contains("metrics")) cols.push_back("metrics=?");
      if (fields.contains("artifacts")) cols.push_back("artifacts=?");
      if (fields.contains("error")) cols.push_back("error=?");
      if (cols.empty()) return true;
      for (size_t i=0;i<cols.size();++i){ if(i) sql<<","; sql<<cols[i]; }
      sql << ", updated_at=CURRENT_TIMESTAMP WHERE id=?";
      std::unique_ptr<sql::PreparedStatement> ps(con->prepareStatement(sql.str()));
      int bind_i = 1;
      if (fields.contains("status")) { ps->setString(bind_i++, fields["status"].get<std::string>()); }
      if (fields.contains("phase")) { ps->setString(bind_i++, fields["phase"].get<std::string>()); }
      if (fields.contains("mlflow_run_id")) { ps->setString(bind_i++, fields["mlflow_run_id"].get<std::string>()); }
      if (fields.contains("registered_model")) { ps->setString(bind_i++, fields["registered_model"].get<std::string>()); }
      if (has_reg_ver) { ps->setInt(bind_i++, reg_ver); }
      if (fields.contains("metrics")) { std::string s = fields["metrics"].dump(); ps->setString(bind_i++, s); }
      if (fields.contains("artifacts")) { std::string s = fields["artifacts"].dump(); ps->setString(bind_i++, s); }
      if (fields.contains("error")) { ps->setString(bind_i++, fields["error"].get<std::string>()); }
      ps->setString(bind_i++, id);
      ps->execute();
      return true;
    } catch (const sql::SQLException& ex) { err_put("jdbc", "train_update", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; }
      catch (const std::exception& ex) { err_put("jdbc", "train_update", { {"msg", ex.what()} }); return false; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      std::ostringstream sql; sql << "UPDATE train_jobs SET ";
      bool first=true;
      auto add = [&](const char* col){ if(first) first=false; else sql << ", "; sql << col << "=:" << col; };
      if (fields.contains("status")) add("status");
      if (fields.contains("phase")) add("phase");
      if (fields.contains("mlflow_run_id")) add("mlflow_run_id");
      if (fields.contains("registered_model")) add("registered_model");
      if (fields.contains("registered_version")) add("registered_version");
      if (fields.contains("metrics")) add("metrics");
      if (fields.contains("artifacts")) add("artifacts");
      if (fields.contains("error")) add("error");
      if (first) return true; // nothing
      sql << ", updated_at=CURRENT_TIMESTAMP WHERE id=:id";
      auto stmt = sess.sql(sql.str());
      if (fields.contains("status")) stmt.bind("status", fields["status"].get<std::string>());
      if (fields.contains("phase")) stmt.bind("phase", fields["phase"].get<std::string>());
      if (fields.contains("mlflow_run_id")) stmt.bind("mlflow_run_id", fields["mlflow_run_id"].get<std::string>());
      if (fields.contains("registered_model")) stmt.bind("registered_model", fields["registered_model"].get<std::string>());
      if (fields.contains("registered_version")) stmt.bind("registered_version", fields["registered_version"].get<int>());
      if (fields.contains("metrics")) stmt.bind("metrics", fields["metrics"].dump());
      if (fields.contains("artifacts")) stmt.bind("artifacts", fields["artifacts"].dump());
      if (fields.contains("error")) stmt.bind("error", fields["error"].get<std::string>());
      stmt.bind("id", id).execute();
      return true;
    } catch (const std::exception& ex) { err_put("mysqlx", "train_update", { {"msg", ex.what()} }); return false; }
  }
#endif
  return false;
}

bool train_job_get_json(const AppConfig& cfg, const std::string& id, std::string* json_out) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) {
    try {
      auto con = jdbc_connect_train(cfg);
      std::unique_ptr<sql::PreparedStatement> ps(con->prepareStatement(
        "SELECT id,status,phase,cfg,mlflow_run_id,registered_model,registered_version,metrics,artifacts,error,created_at,updated_at FROM train_jobs WHERE id=?"));
      ps->setString(1, id);
      std::unique_ptr<sql::ResultSet> rs(ps->executeQuery());
      nlohmann::json o = nlohmann::json::object();
      if (rs->next()) {
        o["id"] = rs->getString(1);
        { std::string v=rs->getString(2); if(!v.empty()) o["status"]=v; }
        { std::string v=rs->getString(3); if(!v.empty()) o["phase"]=v; }
        { std::string v=rs->getString(4); if(!v.empty()) { try { o["cfg"]=nlohmann::json::parse(v); } catch (...) {} } }
        { std::string v=rs->getString(5); if(!v.empty()) o["mlflow_run_id"]=v; }
        { std::string v=rs->getString(6); if(!v.empty()) o["registered_model"]=v; }
        { int v=rs->getInt(7); if(!rs->wasNull()) o["registered_version"]=v; }
        { std::string v=rs->getString(8); if(!v.empty()) { try { o["metrics"]=nlohmann::json::parse(v); } catch (...) {} } }
        { std::string v=rs->getString(9); if(!v.empty()) { try { o["artifacts"]=nlohmann::json::parse(v); } catch (...) {} } }
        { std::string v=rs->getString(10); if(!v.empty()) o["error"]=v; }
        { std::string v=rs->getString(11); if(!v.empty()) o["created_at"]=v; }
        { std::string v=rs->getString(12); if(!v.empty()) o["updated_at"]=v; }
      }
      if (json_out) *json_out = o.dump();
      return true;
    } catch (const sql::SQLException& ex) { err_put("jdbc", "train_get", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; }
      catch (const std::exception& ex) { err_put("jdbc", "train_get", { {"msg", ex.what()} }); return false; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      const char* q =
        "SELECT COALESCE(JSON_OBJECT("
        "'id', id, 'status', status, 'phase', phase, 'cfg', cfg, 'mlflow_run_id', mlflow_run_id,"
        "'registered_model', registered_model, 'registered_version', registered_version,"
        "'metrics', metrics, 'artifacts', artifacts, 'error', error,"
        "'created_at', DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), 'updated_at', DATE_FORMAT(updated_at,'%Y-%m-%d %H:%i:%s')"
        "), JSON_OBJECT()) AS data FROM train_jobs WHERE id = :id";
      auto res = sess.sql(q).bind("id", id).execute();
      auto row = res.fetchOne();
      std::string s = "{}"; if (row) s = std::string(row[0].get<mysqlx::string>());
      if (s.empty()) s = "{}"; if (json_out) *json_out = s; return true;
    } catch (const std::exception& ex) { err_put("mysqlx", "train_get", { {"msg", ex.what()} }); return false; }
  }
#endif
  if (json_out) *json_out = "{}"; return true;
}

bool list_train_jobs_json(const AppConfig& cfg, std::string* json_out) {
#ifdef HAVE_MYSQL_JDBC
  if (use_odbc_mysql(cfg)) {
    try {
      auto con = jdbc_connect_train(cfg);
      std::unique_ptr<sql::Statement> stmt(con->createStatement());
      std::unique_ptr<sql::ResultSet> rs(stmt->executeQuery(
        "SELECT id,status,phase,mlflow_run_id,registered_model,registered_version,created_at,updated_at FROM train_jobs ORDER BY updated_at DESC LIMIT 500"));
      nlohmann::json arr = nlohmann::json::array();
      while (rs->next()) {
        nlohmann::json o; o["id"]=rs->getString(1);
        { std::string v=rs->getString(2); if(!v.empty()) o["status"]=v; }
        { std::string v=rs->getString(3); if(!v.empty()) o["phase"]=v; }
        { std::string v=rs->getString(4); if(!v.empty()) o["mlflow_run_id"]=v; }
        { std::string v=rs->getString(5); if(!v.empty()) o["registered_model"]=v; }
        { int v=rs->getInt(6); if(!rs->wasNull()) o["registered_version"]=v; }
        { std::string v=rs->getString(7); if(!v.empty()) o["created_at"]=v; }
        { std::string v=rs->getString(8); if(!v.empty()) o["updated_at"]=v; }
        arr.push_back(o);
      }
      if (json_out) *json_out = arr.dump();
      return true;
    } catch (const sql::SQLException& ex) { err_put("jdbc", "train_list", { {"code", ex.getErrorCode()}, {"state", ex.getSQLState()}, {"msg", ex.what()} }); return false; }
      catch (const std::exception& ex) { err_put("jdbc", "train_list", { {"msg", ex.what()} }); return false; }
  }
#endif
#ifdef HAVE_MYSQLX
  if (use_mysqlx(cfg)) {
    try {
      mysqlx::Session sess(cfg.db.mysqlx_uri);
      const char* q =
        "SELECT COALESCE(JSON_ARRAYAGG(JSON_OBJECT("
        "'id', id, 'status', status, 'phase', phase, 'mlflow_run_id', mlflow_run_id,"
        "'registered_model', registered_model, 'registered_version', registered_version,"
        "'created_at', DATE_FORMAT(created_at,'%Y-%m-%d %H:%i:%s'), 'updated_at', DATE_FORMAT(updated_at,'%Y-%m-%d %H:%i:%s')"
        ")), JSON_ARRAY()) AS data FROM train_jobs ORDER BY updated_at DESC LIMIT 500";
      if (sql_json_array(sess, q, json_out)) return true;
    } catch (const std::exception& ex) { err_put("mysqlx", "train_list", { {"msg", ex.what()} }); return false; }
  }
#endif
  if (json_out) *json_out = "[]"; return true;
}

} // namespace controlplane::db
