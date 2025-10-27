#include "app/config.hpp"

#include <fstream>
#include <sstream>
#include <algorithm>
#include <cctype>
#include <filesystem>

namespace vsm::app {

static inline std::string trim(const std::string& s) {
  size_t b = 0, e = s.size();
  while (b < e && std::isspace(static_cast<unsigned char>(s[b]))) ++b;
  while (e > b && std::isspace(static_cast<unsigned char>(s[e-1]))) --e;
  return s.substr(b, e - b);
}

static inline std::string unquote(const std::string& s) {
  if (s.size() >= 2 && ((s.front()=='"' && s.back()=='"') || (s.front()=='\'' && s.back()=='\''))) {
    return s.substr(1, s.size()-2);
  }
  return s;
}

static std::string make_abs(const std::string& base_dir, const std::string& path) {
  if (path.empty()) return path;
  std::error_code ec;
  std::filesystem::path p(path);
  if (p.is_absolute()) return path;
  auto abs = std::filesystem::absolute(std::filesystem::path(base_dir) / p, ec);
  return ec ? path : abs.string();
}

bool LoadConfigFromDir(const std::string& config_dir, AppConfig* cfg, std::string* err) {
  if (!cfg) { if (err) *err = "cfg null"; return false; }
  std::filesystem::path f = std::filesystem::path(config_dir) / "app.yaml";
  std::ifstream in(f, std::ios::binary);
  if (!in) { if (err) *err = "open config failed: " + f.string(); return false; }
  std::stringstream ss; ss << in.rdbuf();
  std::string line; std::string cur;
  while (std::getline(ss, line)) {
    std::replace(line.begin(), line.end(), '\t', ' ');
    auto raw = line;
    line = trim(line);
    if (line.empty() || line[0] == '#') continue;
    bool is_top = !raw.empty() && (raw[0] != ' ' && raw[0] != '\t');
    if (is_top) {
      if (line == "server:") { cur = "server"; continue; }
      if (line == "tls:") { cur = "tls"; continue; }
      if (line == "va:") { cur = "va"; continue; }
      if (line == "va.tls:") { cur = "va.tls"; continue; }
    }
    auto pos = line.find(":");
    if (pos == std::string::npos) continue;
    auto k = trim(line.substr(0, pos));
    auto v = trim(line.substr(pos+1));
    v = unquote(v);
    if (cur == "server") {
      if (k == "grpc_listen") cfg->grpc_listen = v;
    } else if (cur == "tls") {
      if (k == "enabled") {
        std::string vv = v; std::transform(vv.begin(), vv.end(), vv.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        cfg->tls.enabled = (vv == "1" || vv == "true" || vv == "on" || vv == "yes");
      } else if (k == "root_cert_file") {
        cfg->tls.root_cert_file = make_abs(config_dir, v);
      } else if (k == "server_cert_file") {
        cfg->tls.server_cert_file = make_abs(config_dir, v);
      } else if (k == "server_key_file") {
        cfg->tls.server_key_file = make_abs(config_dir, v);
      } else if (k == "require_client_cert") {
        std::string vv = v; std::transform(vv.begin(), vv.end(), vv.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        cfg->tls.require_client_cert = (vv == "1" || vv == "true" || vv == "on" || vv == "yes");
      }
    } else if (cur == "va") {
      if (k == "addr") cfg->va.addr = v;
    } else if (cur == "va.tls") {
      if (k == "enabled") {
        std::string vv = v; std::transform(vv.begin(), vv.end(), vv.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        cfg->va.tls.enabled = (vv == "1" || vv == "true" || vv == "on" || vv == "yes");
      } else if (k == "root_cert_file") {
        cfg->va.tls.root_cert_file = make_abs(config_dir, v);
      } else if (k == "client_cert_file") {
        cfg->va.tls.client_cert_file = make_abs(config_dir, v);
      } else if (k == "client_key_file") {
        cfg->va.tls.client_key_file = make_abs(config_dir, v);
      } else if (k == "server_name") {
        cfg->va.tls.server_name = v;
      }
    }
  }
  if (cfg->grpc_listen.empty()) cfg->grpc_listen = "0.0.0.0:7070";
  cfg->tls.root_cert_file = make_abs(config_dir, cfg->tls.root_cert_file);
  cfg->tls.server_cert_file = make_abs(config_dir, cfg->tls.server_cert_file);
  cfg->tls.server_key_file = make_abs(config_dir, cfg->tls.server_key_file);
  cfg->va.addr = cfg->va.addr.empty()? std::string("127.0.0.1:50051") : cfg->va.addr;
  cfg->va.tls.root_cert_file = make_abs(config_dir, cfg->va.tls.root_cert_file);
  cfg->va.tls.client_cert_file = make_abs(config_dir, cfg->va.tls.client_cert_file);
  cfg->va.tls.client_key_file = make_abs(config_dir, cfg->va.tls.client_key_file);
  return true;
}

}
