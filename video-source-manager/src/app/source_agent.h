#pragma once

#include <memory>
#include <string>
#include <unordered_map>
#include <mutex>

namespace vsm { class SourceController; }
namespace vsm::rpc { class GrpcServer; }
namespace vsm::metrics { class MetricsExporter; }

namespace vsm {

class SourceAgent {
public:
  SourceAgent();
  ~SourceAgent();
  bool Start(const std::string& grpc_addr);
  void Stop();
private:
  std::unique_ptr<SourceController> controller_;
  std::unique_ptr<rpc::GrpcServer> grpc_;
  std::unique_ptr<metrics::MetricsExporter> metrics_;
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
