#include "app/controller/source_controller.h"
#include "adapters/inputs/ffmpeg_rtsp_reader.h"
#include "adapters/outputs/to_analyzer_link.h"

namespace vsm {

SourceController::SourceController() = default;
SourceController::~SourceController() = default;

bool SourceController::Attach(const std::string& attach_id, const std::string& source_uri,
                              const std::string& pipeline_id, const std::unordered_map<std::string,std::string>& options,
                              std::string* err) {
  std::lock_guard<std::mutex> lk(mu_);
  if (sessions_.count(attach_id)) { if (err) *err = "already exists"; return false; }
  auto sess = std::make_unique<Session>();
  sess->reader = std::make_unique<FfmpegRtspReader>(source_uri);
  sess->sink = std::make_shared<ToAnalyzerLink>();
  // Accept options.profile/model_id as desired hints for VA
  if (auto it = options.find("profile"); it != options.end()) sess->profile = it->second;
  if (auto it2 = options.find("model_id"); it2 != options.end()) sess->model_id = it2->second;
  if (!sess->reader->Start()) { if (err) *err = "reader start failed"; return false; }
  sess->running.store(true);
  sessions_.emplace(attach_id, std::move(sess));
  // Persist registry best-effort
  try { SaveRegistry(nullptr); } catch (...) {}
  return true;
}

bool SourceController::Detach(const std::string& attach_id, std::string* /*err*/) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = sessions_.find(attach_id);
  if (it == sessions_.end()) return false;
  if (it->second && it->second->reader) it->second->reader->Stop();
  sessions_.erase(it);
  try { SaveRegistry(nullptr); } catch (...) {}
  return true;
}

std::vector<StreamStat> SourceController::Collect() {
  std::vector<StreamStat> out;
  std::lock_guard<std::mutex> lk(mu_);
  for (auto& kv : sessions_) {
    StreamStat st; st.attach_id = kv.first; st.phase = (kv.second && kv.second->running)? "Ready" : "Stopped";
    if (kv.second && kv.second->reader) {
      st.fps = kv.second->reader->Fps();
      st.source_uri = kv.second->reader->Uri();
      st.jitter_ms = kv.second->reader->JitterMs();
      st.rtt_ms = kv.second->reader->RttMs();
      st.loss_pct = kv.second->reader->LossRatio();
      st.last_ok_unixts = kv.second->reader->LastOkUnixSec();
    }
    if (kv.second) { st.profile = kv.second->profile; st.model_id = kv.second->model_id; }
    out.push_back(st);
  }
  return out;
}

bool SourceController::Update(const std::string& attach_id,
                              const std::unordered_map<std::string,std::string>& options,
                              std::string* err) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = sessions_.find(attach_id);
  if (it == sessions_.end()) { if (err) *err = "not found"; return false; }
  auto& sess = it->second;
  if (auto p = options.find("profile"); p != options.end()) sess->profile = p->second;
  if (auto m = options.find("model_id"); m != options.end()) sess->model_id = m->second;
  try { SaveRegistry(nullptr); } catch (...) {}
  return true;
}

bool SourceController::LoadRegistry(std::string* err) {
  std::lock_guard<std::mutex> lk(mu_);
  FILE* f = nullptr;
#ifdef _WIN32
  fopen_s(&f, registry_path_.c_str(), "rb");
#else
  f = std::fopen(registry_path_.c_str(), "rb");
#endif
  if (!f) { if (err) *err = "open registry failed"; return false; }
  char line[2048];
  while (std::fgets(line, sizeof(line), f)) {
    std::string s(line);
    if (!s.empty() && (s.back()=='\n' || s.back()=='\r')) s.pop_back();
    if (s.empty()) continue;
    // split by tab
    std::vector<std::string> cols; cols.reserve(4);
    size_t pos = 0; while (true) { auto t = s.find('\t', pos); if (t==std::string::npos){ cols.emplace_back(s.substr(pos)); break; } cols.emplace_back(s.substr(pos, t-pos)); pos = t+1; if (cols.size()>8) break; }
    if (cols.size() < 2) continue;
    const std::string& id = cols[0]; const std::string& uri = cols[1];
    std::string profile = (cols.size()>2? cols[2] : std::string());
    std::string model   = (cols.size()>3? cols[3] : std::string());
    if (sessions_.count(id)) continue;
    auto sess = std::make_unique<Session>();
    sess->reader = std::make_unique<FfmpegRtspReader>(uri);
    sess->sink = std::make_shared<ToAnalyzerLink>();
    sess->profile = profile; sess->model_id = model;
    if (sess->reader->Start()) { sess->running.store(true); sessions_.emplace(id, std::move(sess)); }
  }
  std::fclose(f);
  return true;
}

bool SourceController::SaveRegistry(std::string* err) {
  std::lock_guard<std::mutex> lk(mu_);
  FILE* f = nullptr;
#ifdef _WIN32
  fopen_s(&f, registry_path_.c_str(), "wb");
#else
  f = std::fopen(registry_path_.c_str(), "wb");
#endif
  if (!f) { if (err) *err = "write registry failed"; return false; }
  for (const auto& kv : sessions_) {
    const auto& id = kv.first;
    const auto* s = kv.second.get(); if (!s || !s->reader) continue;
    const std::string& uri = s->reader->Uri();
    std::fprintf(f, "%s\t%s\t%s\t%s\n", id.c_str(), uri.c_str(), s->profile.c_str(), s->model_id.c_str());
  }
  std::fclose(f);
  return true;
}

} // namespace vsm
