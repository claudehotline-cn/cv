#include "core/wal.hpp"

#include <chrono>
#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <mutex>
#include <deque>
#include <unordered_map>
#include <atomic>
#include <algorithm>

namespace fs = std::filesystem;

namespace va::core::wal {

static std::once_flag g_once;
static bool g_enabled = false;
static fs::path g_path;
static std::mutex g_mu;
static std::atomic<std::uint64_t> g_failed_restart_count{0};
static std::uint64_t g_max_bytes = 5ull * 1024 * 1024; // 5MB
static int g_max_files = 5; // rotated files to keep (excluding active)
static int g_ttl_seconds = 0; // <=0 disabled

static inline std::uint64_t now_ms() {
  using namespace std::chrono;
  return static_cast<std::uint64_t>(duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count());
}

bool enabled() { return g_enabled; }

void init() {
  std::call_once(g_once, [](){
    const char* v = std::getenv("VA_WAL_SUBSCRIPTIONS");
    if (!v) { g_enabled = false; return; }
    std::string s = v; for (auto& c : s) c = (char)tolower((unsigned char)c);
    g_enabled = (s=="1"||s=="true"||s=="yes"||s=="on");
    if (!g_enabled) return;
    try {
      fs::path p = fs::current_path();
      fs::path logs = p / "logs";
      std::error_code ec;
      fs::create_directories(logs, ec);
      g_path = logs / "subscriptions.wal";
      // rolling/ttl config
      if (const char* mb = std::getenv("VA_WAL_MAX_BYTES")) { try { long long x=std::stoll(mb); if (x>1024) g_max_bytes = (std::uint64_t)x; } catch(...){} }
      if (const char* mf = std::getenv("VA_WAL_MAX_FILES")) { try { int x=std::stoi(mf); if (x>=0) g_max_files = x; } catch(...){} }
      if (const char* tt = std::getenv("VA_WAL_TTL_SECONDS")) { try { int x=std::stoi(tt); g_ttl_seconds = x; } catch(...){} }
    } catch (...) {
      g_enabled = false;
    }
  });
}

static void append_line(const std::string& line) {
  if (!g_enabled) return;
  try {
    std::lock_guard<std::mutex> lk(g_mu);
    std::ofstream ofs(g_path, std::ios::out | std::ios::app | std::ios::binary);
    ofs << line << "\n";
    ofs.flush();
    // rolling by size
    std::error_code ec;
    auto sz = fs::file_size(g_path, ec);
    if (!ec && g_max_bytes>0 && sz > g_max_bytes) {
      // rotate to subscriptions.<ts>.wal
      const auto ts = now_ms();
      fs::path rotated = g_path.parent_path() / (std::string("subscriptions.") + std::to_string(ts) + ".wal");
      ofs.close();
      fs::rename(g_path, rotated, ec);
      // recreate active file
      std::ofstream(g_path, std::ios::out | std::ios::trunc | std::ios::binary).close();
      // cleanup by count
      std::vector<std::pair<fs::path, std::uint64_t>> files;
      for (auto& p : fs::directory_iterator(g_path.parent_path(), ec)) {
        if (ec) break;
        auto name = p.path().filename().string();
        if (name.rfind("subscriptions",0)==0 && name.find(".wal")!=std::string::npos) {
          auto wt = (std::uint64_t)fs::last_write_time(p.path(), ec).time_since_epoch().count();
          files.emplace_back(p.path(), wt);
        }
      }
      std::sort(files.begin(), files.end(), [](auto& a, auto& b){ return a.second < b.second; });
      // keep newest (active + g_max_files rotated)
      int keep = g_max_files + 1;
      while ((int)files.size() > keep) { fs::remove(files.front().first, ec); files.erase(files.begin()); }
      // ttl cleanup
      if (g_ttl_seconds > 0) {
        auto nowf = fs::file_time_type::clock::now();
        for (auto& kv : files) {
          std::error_code ec2;
          auto ftime = fs::last_write_time(kv.first, ec2);
          if (!ec2) {
            auto age = std::chrono::duration_cast<std::chrono::seconds>(nowf - ftime).count();
            if (age >= g_ttl_seconds) fs::remove(kv.first, ec2);
          }
        }
      }
    }
  } catch (...) { /* best-effort */ }
}

static std::string esc(const std::string& s) {
  std::string out; out.reserve(s.size()+8);
  for (char c : s) {
    if (c=='\\' || c=='"') { out.push_back('\\'); out.push_back(c); }
    else if ((unsigned char)c < 0x20) { out.push_back(' '); }
    else out.push_back(c);
  }
  return out;
}

void append_subscription_event(const std::string& op,
                               const std::string& sub_id,
                               const std::string& base_key,
                               const std::string& phase,
                               const std::string& reason_code,
                               std::uint64_t ts_pending,
                               std::uint64_t ts_preparing,
                               std::uint64_t ts_opening,
                               std::uint64_t ts_loading,
                               std::uint64_t ts_starting,
                               std::uint64_t ts_ready,
                               std::uint64_t ts_failed,
                               std::uint64_t ts_cancelled) {
  if (!g_enabled) return;
  std::string line;
  line.reserve(256);
  line += '{';
  line += "\"ts\":" + std::to_string(now_ms());
  line += ",\"op\":\"" + esc(op) + "\"";
  line += ",\"id\":\"" + esc(sub_id) + "\"";
  line += ",\"base_key\":\"" + esc(base_key) + "\"";
  if (!phase.empty()) line += ",\"phase\":\"" + esc(phase) + "\"";
  if (!reason_code.empty()) line += ",\"reason\":\"" + esc(reason_code) + "\"";
  line += ",\"timeline\":{"
          "\"pending\":" + std::to_string(ts_pending) +
          ",\"preparing\":" + std::to_string(ts_preparing) +
          ",\"opening_rtsp\":" + std::to_string(ts_opening) +
          ",\"loading_model\":" + std::to_string(ts_loading) +
          ",\"starting_pipeline\":" + std::to_string(ts_starting) +
          ",\"ready\":" + std::to_string(ts_ready) +
          ",\"failed\":" + std::to_string(ts_failed) +
          ",\"cancelled\":" + std::to_string(ts_cancelled) +
          '}';
  line += '}';
  append_line(line);
}

void mark_restart() {
  if (!g_enabled) return;
  append_line(std::string("{\"ts\":") + std::to_string(now_ms()) + ",\"op\":\"restart\"}");
}

void scanInflightBeforeLastRestart() {
  if (!g_enabled) { g_failed_restart_count.store(0, std::memory_order_relaxed); return; }
  std::vector<std::string> lines;
  try {
    std::lock_guard<std::mutex> lk(g_mu);
    std::ifstream ifs(g_path, std::ios::in | std::ios::binary);
    std::string line;
    while (std::getline(ifs, line)) {
      if (!line.empty() && (line.back()=='\r' || line.back()=='\n')) line.pop_back();
      lines.push_back(line);
    }
  } catch (...) { lines.clear(); }
  // 找到最近一次 restart 的位置（当前进程启动时 mark_restart 已写入一条）
  int last_restart = -1;
  for (int i=0;i<(int)lines.size();++i) {
    if (lines[i].find("\"op\":\"restart\"") != std::string::npos) last_restart = i;
  }
  const int end_idx = (last_restart >= 0) ? last_restart : (int)lines.size();
  // 粗略聚合：base_key -> (seen_enqueue, seen_terminal)
  struct Flags { bool enq=false; bool term=false; };
  std::unordered_map<std::string, Flags> mp;
  auto extract = [](const std::string& s, const char* key)->std::string{
    std::string pat = std::string("\"") + key + "\":\"";
    auto p = s.find(pat);
    if (p==std::string::npos) return {};
    p += pat.size();
    auto q = s.find('"', p);
    if (q==std::string::npos) return {};
    return s.substr(p, q-p);
  };
  for (int i=0;i<end_idx;i++) {
    const std::string& s = lines[i];
    const std::string op = extract(s, "op");
    const std::string bk = extract(s, "base_key");
    if (bk.empty() || op.empty()) continue;
    auto& f = mp[bk];
    if (op == "enqueue") f.enq = true;
    if (op == "ready" || op == "failed" || op == "cancelled") f.term = true;
  }
  std::uint64_t inflight = 0;
  for (const auto& kv : mp) {
    if (kv.second.enq && !kv.second.term) inflight++;
  }
  g_failed_restart_count.store(inflight, std::memory_order_relaxed);
}

std::uint64_t failedRestartCount() {
  return g_failed_restart_count.load(std::memory_order_relaxed);
}

std::vector<std::string> tail(std::size_t n) {
  std::vector<std::string> out;
  if (!g_enabled || n==0) return out;
  try {
    std::lock_guard<std::mutex> lk(g_mu);
    std::ifstream ifs(g_path, std::ios::in | std::ios::binary);
    std::deque<std::string> dq;
    std::string line;
    while (std::getline(ifs, line)) {
      if (!line.empty() && (line.back()=='\r' || line.back()=='\n')) line.pop_back();
      dq.push_back(line);
      if (dq.size() > n) dq.pop_front();
    }
    out.assign(dq.begin(), dq.end());
  } catch (...) {}
  return out;
}

} // namespace va::core::wal
