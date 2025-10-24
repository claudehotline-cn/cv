#include "analyzer/model_registry.hpp"

#include "ConfigLoader.hpp"

#include <algorithm>
#include <cstdlib>
#include <thread>

namespace va::analyzer {

ModelRegistry& ModelRegistry::instance() {
  static ModelRegistry g;
  return g;
}

void ModelRegistry::configureFromEnv() {
  const char* en = std::getenv("VA_MODEL_REGISTRY_ENABLED");
  if (en) {
    std::string s = en; std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return (char)std::tolower(c); });
    enabled_ = (s=="1"||s=="true"||s=="on"||s=="yes");
  }
  if (const char* p = std::getenv("VA_MODEL_REGISTRY_CAP")) {
    try { std::size_t v = static_cast<std::size_t>(std::stoll(p)); if (v>0) capacity_ = v; } catch (...) {}
  }
  if (const char* p = std::getenv("VA_MODEL_IDLE_TTL_SEC")) {
    try { int v = std::stoi(p); if (v>=0) idle_ttl_sec_ = v; } catch (...) {}
  }
}

void ModelRegistry::configurePreheatFromEnv() {
  const char* en = std::getenv("VA_MODEL_PREHEAT_ENABLED");
  if (en) { std::string s=en; std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){return (char)std::tolower(c);}); preheat_enabled_ = (s=="1"||s=="true"||s=="on"||s=="yes"); }
  if (const char* c = std::getenv("VA_MODEL_PREHEAT_CONCURRENCY")) { try { int v=std::stoi(c); if (v>0) preheat_concurrency_ = v; } catch (...) {} }
  if (const char* lst = std::getenv("VA_MODEL_PREHEAT_LIST")) {
    std::string s = lst; std::vector<std::string> arr; std::string cur; for (char ch : s){ if (ch==','||ch==';'||ch==' '){ if(!cur.empty()){arr.push_back(cur);cur.clear();} } else cur.push_back(ch);} if(!cur.empty()) arr.push_back(cur);
    if (!arr.empty()) schedulePreheat(arr);
  }
}

void ModelRegistry::setEnabled(bool on) { std::lock_guard<std::mutex> lk(mu_); enabled_ = on; }
bool ModelRegistry::enabled() const { std::lock_guard<std::mutex> lk(mu_); return enabled_; }
void ModelRegistry::setCapacity(std::size_t cap) { std::lock_guard<std::mutex> lk(mu_); if (cap>0) capacity_ = cap; }
void ModelRegistry::setIdleTtlSeconds(int sec) { std::lock_guard<std::mutex> lk(mu_); if (sec>=0) idle_ttl_sec_ = sec; }

void ModelRegistry::setModels(const std::vector<DetectionModelEntry>& models) {
  std::lock_guard<std::mutex> lk(mu_);
  for (const auto& m : models) {
    if (m.id.empty()) continue;
    auto it = entries_.find(m.id);
    if (it == entries_.end()) {
      ModelMeta meta; meta.id = m.id; meta.task = m.task; meta.path = m.path; meta.provider.clear(); meta.device = 0; meta.last_used = std::chrono::system_clock::now();
      entries_.emplace(m.id, std::move(meta));
    }
  }
  pruneIdleLocked();
}

void ModelRegistry::touch(const std::string& model_id) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = entries_.find(model_id);
  if (it != entries_.end()) it->second.last_used = std::chrono::system_clock::now();
}

void ModelRegistry::schedulePreheat(const std::vector<std::string>& model_ids) {
  std::lock_guard<std::mutex> lk(mu_);
  preheat_list_.assign(model_ids.begin(), model_ids.end());
}

void ModelRegistry::pruneIdleLocked() {
  if (!enabled_) return;
  if (idle_ttl_sec_ <= 0) return;
  const auto now = std::chrono::system_clock::now();
  for (auto it = entries_.begin(); it != entries_.end(); ) {
    auto age = std::chrono::duration_cast<std::chrono::seconds>(now - it->second.last_used).count();
    if (age >= idle_ttl_sec_ && entries_.size() > 1) {
      it = entries_.erase(it);
    } else {
      ++it;
    }
  }
  // capacity enforcement（近似）：若超限则按 last_used 最早淘汰
  if (entries_.size() > capacity_) {
    std::vector<std::pair<std::string, std::chrono::system_clock::time_point>> arr;
    arr.reserve(entries_.size());
    for (const auto& kv : entries_) arr.emplace_back(kv.first, kv.second.last_used);
    std::sort(arr.begin(), arr.end(), [](auto& a, auto& b){ return a.second < b.second; });
    std::size_t remove_n = entries_.size() - capacity_;
    for (std::size_t i=0; i<remove_n && i<arr.size(); ++i) entries_.erase(arr[i].first);
  }
}

void ModelRegistry::startPreheat() {
  std::lock_guard<std::mutex> lk(mu_);
  if (!preheat_enabled_ || preheat_list_.empty() || preheat_thread_spawned_) return;
  preheat_thread_spawned_ = true;
  preheat_status_ = PreheatStatus::Running;
  warmed_ = 0;
  std::thread([this](){ this->runPreheat(); }).detach();
}

void ModelRegistry::runPreheat() {
  std::vector<std::string> items;
  {
    std::lock_guard<std::mutex> lk(mu_);
    items = preheat_list_;
  }
  // 简化：顺序触发 touch（不实际加载会话，避免影响运行管线）。限制速率：每个条目 sleep 50ms，并尊重并发上限
  // （骨架阶段：并发上限仅作为节流参数使用）
  const int limit = std::max(1, preheat_concurrency_);
  int in_flight = 0; size_t idx = 0;
  std::mutex m;
  auto worker = [this,&m](std::string id){
    this->touch(id);
    std::this_thread::sleep_for(std::chrono::milliseconds(50));
    std::lock_guard<std::mutex> lk(m);
    warmed_ += 1;
  };
  std::vector<std::thread> threads;
  while (idx < items.size()) {
    while (in_flight < limit && idx < items.size()) {
      threads.emplace_back(worker, items[idx++]);
      in_flight++;
    }
    if (in_flight >= limit) {
      threads.front().join(); threads.erase(threads.begin()); in_flight--;
    }
  }
  for (auto& t : threads) if (t.joinable()) t.join();
  {
    std::lock_guard<std::mutex> lk(mu_);
    preheat_status_ = PreheatStatus::Done;
  }
}

bool ModelRegistry::preheatEnabled() const { std::lock_guard<std::mutex> lk(mu_); return preheat_enabled_; }
int ModelRegistry::preheatConcurrency() const { std::lock_guard<std::mutex> lk(mu_); return preheat_concurrency_; }
std::vector<std::string> ModelRegistry::preheatList() const { std::lock_guard<std::mutex> lk(mu_); return preheat_list_; }
std::string ModelRegistry::preheatStatus() const { std::lock_guard<std::mutex> lk(mu_); switch(preheat_status_){case PreheatStatus::Idle: return "idle"; case PreheatStatus::Running: return "running"; default: return "done";} }
int ModelRegistry::warmedCount() const { std::lock_guard<std::mutex> lk(mu_); return warmed_; }

} // namespace va::analyzer
