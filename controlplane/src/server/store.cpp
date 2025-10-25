#include "controlplane/store.hpp"
#include <random>

namespace controlplane {

Store& Store::instance() {
  static Store s; return s;
}

long long Store::now_ms() {
  using namespace std::chrono;
  return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

std::string Store::gen_cp_id() {
  auto n = ++seq_;
  // simple unique id: cp-<epochms>-<seq>
  return std::string("cp-") + std::to_string(now_ms()) + "-" + std::to_string(n);
}

std::string Store::create(const std::string& stream_id,
                          const std::string& profile,
                          const std::string& source_uri,
                          const std::string& model_id,
                          const std::string& va_subscription_id) {
  std::lock_guard<std::mutex> lk(mu_);
  std::string id = gen_cp_id();
  SubscriptionRecord r;
  r.cp_id = id;
  r.stream_id = stream_id;
  r.profile = profile;
  r.source_uri = source_uri;
  r.model_id = model_id;
  r.va_subscription_id = va_subscription_id;
  r.last = TimelineEvent{ "pending", now_ms(), "" };
  r.version = 1;
  m_[id] = r;
  return id;
}

std::optional<SubscriptionRecord> Store::get(const std::string& cp_id) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = m_.find(cp_id);
  if (it == m_.end()) return std::nullopt;
  return it->second;
}

void Store::set_phase(const std::string& cp_id, const std::string& phase, const std::string& reason) {
  std::lock_guard<std::mutex> lk(mu_);
  auto it = m_.find(cp_id);
  if (it == m_.end()) return;
  it->second.last.phase = phase;
  it->second.last.reason = reason;
  it->second.last.ts_ms = now_ms();
  it->second.version++;
}

void Store::erase(const std::string& cp_id) {
  std::lock_guard<std::mutex> lk(mu_);
  m_.erase(cp_id);
}

std::string Store::make_etag(const SubscriptionRecord& r) {
  return std::string("W\"") + std::to_string(r.version) + "\"";
}

} // namespace controlplane


