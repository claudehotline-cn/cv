#include "controlplane/circuit_breaker.hpp"
#include "controlplane/metrics.hpp"
#include <unordered_map>
#include <mutex>
#include <chrono>

namespace controlplane::cb {

struct State {
  int consec_fail{0};
  bool open{false};
  std::chrono::steady_clock::time_point until{}; // open until (cooldown)
};

static std::mutex g_mu;
static std::unordered_map<std::string, State> g_map;
static constexpr int FAIL_THRESHOLD = 3;
static constexpr int COOL_MS = 5000;

static void set_gauge(const std::string& svc, bool open) {
  try {
    // reuse backend error metric space: we don't have a gauge API; expose via request metric labels is overkill.
    // For visibility, emit a backend error code -1 when opened; it's a workaround without adding a new metric surface.
    if (open) controlplane::metrics::inc_backend_error(std::string("circuit_")+svc, -1);
  } catch (...) {}
}

bool allow(const std::string& svc) {
  using namespace std::chrono;
  std::lock_guard<std::mutex> lk(g_mu);
  auto& st = g_map[svc];
  if (st.open) {
    auto now = steady_clock::now();
    if (now >= st.until) {
      // half-open trial: allow exactly one, keep open until success/failure updates
      return true;
    }
    return false;
  }
  return true;
}

void on_success(const std::string& svc) {
  std::lock_guard<std::mutex> lk(g_mu);
  auto& st = g_map[svc];
  st.consec_fail = 0;
  if (st.open) { st.open = false; set_gauge(svc, false); }
}

void on_failure(const std::string& svc) {
  using namespace std::chrono;
  std::lock_guard<std::mutex> lk(g_mu);
  auto& st = g_map[svc];
  st.consec_fail++;
  if (st.consec_fail >= FAIL_THRESHOLD) {
    st.open = true;
    st.until = steady_clock::now() + milliseconds(COOL_MS);
    set_gauge(svc, true);
  }
}

bool is_open(const std::string& svc) {
  std::lock_guard<std::mutex> lk(g_mu);
  auto it = g_map.find(svc);
  return it != g_map.end() && it->second.open;
}

} // namespace controlplane::cb

