#include "app/controller/source_controller.h"
#include "adapters/inputs/ffmpeg_rtsp_reader.h"
#include "adapters/outputs/to_analyzer_link.h"

namespace vsm {

SourceController::SourceController() = default;
SourceController::~SourceController() = default;

bool SourceController::Attach(const std::string& attach_id, const std::string& source_uri,
                              const std::string& /*pipeline_id*/, const std::unordered_map<std::string,std::string>& /*options*/,
                              std::string* err) {
  std::lock_guard<std::mutex> lk(mu_);
  if (sessions_.count(attach_id)) { if (err) *err = "already exists"; return false; }
  auto sess = std::make_unique<Session>();
  sess->reader = std::make_unique<FfmpegRtspReader>(source_uri);
  sess->sink = std::make_shared<ToAnalyzerLink>();
  if (!sess->reader->Start()) { if (err) *err = "reader start failed"; return false; }
  sess->running.store(true);
  sessions_.emplace(attach_id, std::move(sess));
  return true;
}

bool SourceController::Detach(const std::string& attach_id, std::string* /*err*/) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = sessions_.find(attach_id);
  if (it == sessions_.end()) return false;
  if (it->second && it->second->reader) it->second->reader->Stop();
  sessions_.erase(it);
  return true;
}

std::vector<StreamStat> SourceController::Collect() {
  std::vector<StreamStat> out;
  std::lock_guard<std::mutex> lk(mu_);
  for (auto& kv : sessions_) {
    StreamStat st; st.attach_id = kv.first; st.phase = (kv.second && kv.second->running)? "Ready" : "Stopped";
    if (kv.second && kv.second->reader) st.fps = kv.second->reader->Fps();
    out.push_back(st);
  }
  return out;
}

} // namespace vsm
