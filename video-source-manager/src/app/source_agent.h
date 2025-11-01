#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <vector>
#include <mutex>
#include "app/config.hpp"

namespace vsm { class SourceController; }
namespace vsm::rpc { class GrpcServer; }
namespace vsm::metrics { class MetricsExporter; }

namespace vsm {

class SourceAgent {
public:
  SourceAgent();
  ~SourceAgent();
  bool Start(const std::string& grpc_addr);
  // 配置驱动启动（推荐）：从 AppConfig 注入 TLS 与监听地址
  bool Start(const vsm::app::AppConfig& cfg);
  void Stop();
private:
  std::unique_ptr<SourceController> controller_;
  std::unique_ptr<rpc::GrpcServer> grpc_;
  std::unique_ptr<metrics::MetricsExporter> metrics_;
  bool has_tls_cfg_ {false};
  vsm::app::TlsConfig tls_cfg_;
  bool has_va_client_cfg_ {false};
  vsm::app::VaClientConfig va_client_cfg_;
  // REST metrics (per-path counters and duration histogram)
  std::mutex rest_mu_;
  std::unordered_map<std::string, std::unordered_map<std::string, unsigned long long>> rest_totals_by_code_; // path -> code -> total
  std::unordered_map<std::string, std::vector<unsigned long long>> rest_hist_buckets_; // path -> buckets
  std::unordered_map<std::string, double> rest_hist_sum_;
  std::unordered_map<std::string, unsigned long long> rest_hist_count_;
  const std::vector<double> rest_bounds_ {0.005,0.01,0.025,0.05,0.1,0.25,0.5,1.0,2.5,5.0,10.0};
  void RecordRestMetric(const std::string& path, const std::string& code, double seconds);
};

} // namespace vsm
