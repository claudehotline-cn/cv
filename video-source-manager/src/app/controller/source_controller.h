#pragma once

#include <string>
#include <unordered_map>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>

namespace vsm {

class FfmpegRtspReader;
class ToAnalyzerLink;

struct StreamStat {
  std::string attach_id;
  std::string source_uri;
  std::string profile;
  std::string model_id;
  double fps {0.0};
  double rtt_ms {0.0};
  double jitter_ms {0.0};
  double loss_pct {0.0};
  std::string phase {"Ready"};
  uint64_t last_ok_unixts {0};
};

class SourceController {
public:
  SourceController();
  ~SourceController();

  bool Attach(const std::string& attach_id, const std::string& source_uri,
              const std::string& pipeline_id,
              const std::unordered_map<std::string,std::string>& options,
              std::string* err);
  bool Detach(const std::string& attach_id, std::string* err);
  bool Update(const std::string& attach_id,
              const std::unordered_map<std::string,std::string>& options,
              std::string* err);
  std::vector<StreamStat> Collect();

  // Registry persistence (simple TSV: attach_id \t uri \t profile \t model_id)
  void SetRegistryPath(const std::string& path) { std::lock_guard<std::mutex> lk(mu_); registry_path_ = path; }
  bool LoadRegistry(std::string* err);
  bool SaveRegistry(std::string* err);

private:
  struct Session {
    std::unique_ptr<FfmpegRtspReader> reader;
    std::shared_ptr<ToAnalyzerLink>   sink;
    std::string profile;   // desired VA profile id hint
    std::string model_id;  // desired VA model id hint
    std::atomic<bool> running{false};
  };
  std::mutex mu_;
  std::unordered_map<std::string, std::unique_ptr<Session>> sessions_; // attach_id -> Session
  std::string registry_path_ {"vsm_registry.tsv"};
};

} // namespace vsm
