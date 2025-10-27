#pragma once

#include <string>

namespace vsm::app {

struct TlsConfig {
  bool enabled { true };
  std::string root_cert_file;
  std::string server_cert_file;
  std::string server_key_file;
  bool require_client_cert { true };
};

struct ClientTlsConfig {
  bool enabled { true };
  std::string root_cert_file;   // CA bundle
  std::string client_cert_file; // client certificate (mTLS)
  std::string client_key_file;  // client private key (mTLS)
  std::string server_name {"localhost"}; // SNI/authority
};

struct VaClientConfig {
  std::string addr {"127.0.0.1:50051"};
  ClientTlsConfig tls;
};

struct AppConfig {
  std::string grpc_listen {"0.0.0.0:7070"};
  TlsConfig tls;
  VaClientConfig va; // outbound to VideoAnalyzer
};

// Parse a minimal YAML subset from app.yaml under config_dir.
// Returns true on success and fills out cfg; tolerates missing keys.
bool LoadConfigFromDir(const std::string& config_dir, AppConfig* cfg, std::string* err);

}
