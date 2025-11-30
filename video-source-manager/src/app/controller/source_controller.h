#pragma once

#include <string>
#include <unordered_map>
#include <vector>
#include <memory>
#include <mutex>
#include <atomic>
#include <condition_variable>

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
  // caps (optional)
  int width {0};
  int height {0};
  std::string codec;
  std::string pix_fmt;
  std::string color_space;
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
  bool GetOne(const std::string& attach_id, StreamStat* out);
  uint64_t Revision() const { return revision_.load(); }
  std::pair<uint64_t, std::vector<StreamStat>> Snapshot();
  // Block until revision changes or timeout_ms elapses. Returns new_rev.
  bool WaitForChange(uint64_t since, int timeout_ms, uint64_t* new_rev);

  // Registry persistence (simple TSV: attach_id \t uri \t profile \t model_id)
  void SetRegistryPath(const std::string& path) { std::lock_guard<std::mutex> lk(mu_); registry_path_ = path; }
  bool LoadRegistry(std::string* err);
  bool SaveRegistry(std::string* err);

private:
  bool LoadRegistryNoLock(std::string* err);
  bool SaveRegistryNoLock(std::string* err);

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
  std::atomic<uint64_t> revision_{0};
  std::condition_variable cv_;
};

} // namespace vsm
