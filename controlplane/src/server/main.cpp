#include <iostream>
#include "controlplane/db.hpp"
#include "controlplane/manifest.hpp"
#include <string>
#include <thread>
#include <chrono>
#include <sstream>
#include <cstring>
#include <cctype>
#include <cstdlib>
#include <nlohmann/json.hpp>
#include <fstream>
#include <filesystem>
#include <unordered_map>
#include <atomic>

#include "controlplane/config.hpp"
#include "controlplane/http_server.hpp"
#include "controlplane/store.hpp"
#include "controlplane/grpc_clients.hpp"
#include "controlplane/watch_adapter.hpp"
#include "controlplane/sse_utils.hpp"
#include "controlplane/metrics.hpp"
#include "controlplane/cache.hpp"
#include "controlplane/logging.hpp"
#include "controlplane/http_proxy.hpp"
#include "controlplane/db.hpp"

#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "source_control.grpc.pb.h"

namespace controlplane { bool quick_probe_va(const std::string&); bool quick_probe_vsm(const std::string&); }

namespace {
struct ErrMap { int code; const char* text; };
inline ErrMap cp_map_err(const std::string& emsg) {
  // Prefer precise gRPC status mapping when available
  int gcode = controlplane::last_grpc_status_code();
  switch (gcode) {
    case grpc::StatusCode::INVALID_ARGUMENT: return {400, "INVALID_ARGUMENT"};
    case grpc::StatusCode::NOT_FOUND: return {404, "NOT_FOUND"};
    case grpc::StatusCode::ALREADY_EXISTS: return {409, "CONFLICT"};
    case grpc::StatusCode::FAILED_PRECONDITION: return {409, "CONFLICT"};
    case grpc::StatusCode::UNAVAILABLE: return {503, "UNAVAILABLE"};
    case grpc::StatusCode::DEADLINE_EXCEEDED: return {504, "TIMEOUT"};
    case grpc::StatusCode::CANCELLED: return {499, "CLIENT_CLOSED"};
    default: break;
  }
  // Fallback to message heuristics
  ErrMap out{502, "BACKEND_ERROR"};
  std::string s = emsg; for (auto& c : s) c = (char)tolower((unsigned char)c);
  auto has = [&](const char* k){ return s.find(k) != std::string::npos; };
  if (has("invalid") || has("bad arg") || has("missing")) { out = {400, "INVALID_ARGUMENT"}; }
  else if (has("already exists") || has("conflict") || has("busy") || has("in use")) { out = {409, "CONFLICT"}; }
  else if (has("not found") || has("no such") || has("unknown")) { out = {404, "NOT_FOUND"}; }
  return out;
}

// Minimal in-memory job store for ONNX->TensorRT plan conversion
struct ConvertJob {
  std::mutex mu;
  std::vector<std::string> logs;
  std::string phase; // created|running|uploading|done|failed
  int exit_code{0};
  bool uploaded{false};
};
static std::mutex g_conv_mu;
static std::unordered_map<std::string, std::shared_ptr<ConvertJob>> g_conv_jobs;
static std::string gen_job_id() {
  auto now = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
  std::ostringstream os; os << std::hex << now; return os.str();
}

static void append_log(std::shared_ptr<ConvertJob> job, const std::string& line) {
  std::lock_guard<std::mutex> lk(job->mu);
  job->logs.push_back(line);
}

static int run_trtexec_and_upload(const std::string& trtexec_cmd,
                                  const std::string& plan_path,
                                  const std::string& va_addr,
                                  const std::string& model,
                                  const std::string& version,
                                  std::shared_ptr<ConvertJob> job) {
  {
    std::lock_guard<std::mutex> lk(job->mu);
    job->phase = "running";
  }
  FILE* fp = popen((trtexec_cmd + " 2>&1").c_str(), "r");
  if (fp) {
    char buf[1024];
    while (true) {
      size_t n = fread(buf, 1, sizeof(buf)-1, fp);
      if (n == 0) break;
      buf[n] = 0;
      // split lines
      std::string chunk(buf);
      size_t start = 0; size_t pos;
      while ((pos = chunk.find('\n', start)) != std::string::npos) {
        append_log(job, chunk.substr(start, pos-start));
        start = pos + 1;
      }
      if (start < chunk.size()) append_log(job, chunk.substr(start));
    }
    int rc = pclose(fp);
    job->exit_code = rc;
  } else {
    append_log(job, "failed to start trtexec");
    job->exit_code = -1;
  }
  if (job->exit_code != 0) {
    std::lock_guard<std::mutex> lk(job->mu);
    job->phase = "failed";
    return job->exit_code;
  }
  {
    std::lock_guard<std::mutex> lk(job->mu);
    job->phase = "uploading";
  }
  // Read plan and upload via VA
  std::string plan_bytes;
  try {
    std::ifstream ifs(plan_path, std::ios::binary);
    plan_bytes.assign(std::istreambuf_iterator<char>(ifs), std::istreambuf_iterator<char>());
  } catch (...) {}
  if (plan_bytes.empty()) {
    append_log(job, "engine file missing");
    std::lock_guard<std::mutex> lk(job->mu);
    job->phase = "failed"; return -2;
  }
  std::string err;
  bool ok = controlplane::va_repo_put_file(va_addr, model, version, "model.plan", plan_bytes, &err);
  if (!ok) {
    append_log(job, std::string("upload failed: ") + err);
    std::lock_guard<std::mutex> lk(job->mu);
    job->phase = "failed"; return -3;
  }
  {
    std::lock_guard<std::mutex> lk(job->mu);
    job->uploaded = true; job->phase = "done";
  }
  append_log(job, "upload ok: model.plan");
  return 0;
}
}

// -------------------- Training (skeleton) --------------------
struct TrainEvent { std::string kind; std::string json; };
struct TrainJobRec {
  std::mutex mu;
  std::string status{"created"};
  std::string phase{"created"};
  double progress{0.0};
  std::vector<TrainEvent> events; // ordered
  bool done{false};
};
static std::mutex g_train_mu;
static std::unordered_map<std::string, std::shared_ptr<TrainJobRec>> g_train_jobs;
static std::string gen_train_job_id() { return std::string("t_") + gen_job_id(); }

static void train_emit(std::shared_ptr<TrainJobRec> tj, const std::string& kind, const std::string& json) {
  std::lock_guard<std::mutex> lk(tj->mu);
  tj->events.push_back({kind, json});
}

// Minimal simulator to provide SSE semantics before real trainer integration
static void launch_train_simulator(const controlplane::AppConfig& cfg,
                                   const std::string& job_id,
                                   const nlohmann::json& cfg_json) {
  std::shared_ptr<TrainJobRec> tj;
  {
    std::lock_guard<std::mutex> lk(g_train_mu);
    auto it = g_train_jobs.find(job_id);
    if (it == g_train_jobs.end()) return; tj = it->second;
  }
  // persist created
  try { controlplane::db::train_job_create(cfg, job_id, "created", "preparing", cfg_json); } catch (...) {}
  {
    std::lock_guard<std::mutex> lk(tj->mu);
    tj->status = "running"; tj->phase = "preparing"; tj->progress = 0.0;
  }
  train_emit(tj, "state", "{\"phase\":\"preparing\",\"progress\":0}");
  std::this_thread::sleep_for(std::chrono::seconds(1));
  {
    std::lock_guard<std::mutex> lk(tj->mu);
    tj->phase = "running"; tj->progress = 0.05;
  }
  train_emit(tj, "state", "{\"phase\":\"running\",\"progress\":0.05}");
  for (int i=1;i<=10;i++) {
    std::this_thread::sleep_for(std::chrono::milliseconds(500));
    double p = 0.05 + 0.07*i; if (p>0.8) p=0.8;
    {
      std::lock_guard<std::mutex> lk(tj->mu); tj->progress = p;
    }
    std::ostringstream js; js << "{\"phase\":\"running\",\"progress\":" << p << "}";
    train_emit(tj, "state", js.str());
  }
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->phase = "exporting"; tj->progress = 0.85;
  }
  train_emit(tj, "state", "{\"phase\":\"exporting\",\"progress\":0.85}");
  std::this_thread::sleep_for(std::chrono::seconds(1));
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->phase = "deploying"; tj->progress = 0.95;
  }
  train_emit(tj, "state", "{\"phase\":\"deploying\",\"progress\":0.95}");
  std::this_thread::sleep_for(std::chrono::seconds(1));
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->status = "done"; tj->phase = "done"; tj->progress = 1.0; tj->done = true;
  }
  train_emit(tj, "done", "{\"phase\":\"done\",\"progress\":1}");
  try { controlplane::db::train_job_update(cfg, job_id, { {"status","done"}, {"phase","done"} }); } catch (...) {}
}

static std::string write_yaml_cfg_to_tmp(const nlohmann::json& j, const std::string& job_id) {
  const char* shared = std::getenv("CP_TRAINER_SHARED_DIR");
  std::string path;
  if (shared && *shared) {
    std::filesystem::create_directories(shared);
    std::ostringstream p; p << shared;
    std::string dir = p.str();
    if (!dir.empty() && dir.back() != '/' && dir.back() != '\\') dir += '/';
    path = dir + job_id + ".yaml";
  } else {
    std::ostringstream p; p << "/tmp/train_" << job_id << ".yaml";
    path = p.str();
  }
  try { std::ofstream ofs(path, std::ios::binary); ofs << j.dump(2); ofs.close(); } catch (...) {}
  return path;
}

// Launch external trainer subprocess (if CP_TRAINER_CMD provided), else caller should fall back to simulator
static void launch_trainer_subprocess(const controlplane::AppConfig& cfg,
                                      const std::string& job_id,
                                      const nlohmann::json& cfg_json) {
  std::shared_ptr<TrainJobRec> tj;
  {
    std::lock_guard<std::mutex> lk(g_train_mu);
    auto it = g_train_jobs.find(job_id);
    if (it == g_train_jobs.end()) return; tj = it->second;
  }
  // persist created
  try { controlplane::db::train_job_create(cfg, job_id, "created", "preparing", cfg_json); } catch (...) {}
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->status = "running"; tj->phase = "preparing"; tj->progress = 0.0;
  }
  train_emit(tj, "state", "{\"phase\":\"preparing\",\"progress\":0}");

  std::string cfg_path = write_yaml_cfg_to_tmp(cfg_json, job_id);
  std::string cmd;
  const char* env_cmd = std::getenv("CP_TRAINER_CMD");
  const char* mlflow_uri = std::getenv("CP_MLFLOW_TRACKING_URI");
  std::string env_prefix;
  if (mlflow_uri && *mlflow_uri) {
    env_prefix = std::string("MLFLOW_TRACKING_URI=") + mlflow_uri + " ";
  }
  if (env_cmd && *env_cmd) {
    cmd = env_cmd;
    auto pos = cmd.find("{config}");
    if (pos != std::string::npos) cmd.replace(pos, 8, cfg_path);
    else { cmd += " -c "; cmd += cfg_path; }
  } else {
    cmd = std::string("python3 -m model_trainer.entry -c ") + cfg_path;
  }
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->phase = "running"; tj->progress = 0.05;
  }
  train_emit(tj, "state", "{\"phase\":\"running\",\"progress\":0.05}");

  FILE* fp = popen((env_prefix + cmd + " 2>&1").c_str(), "r");
  if (!fp) { train_emit(tj, "error", "{\"msg\":\"failed to start trainer\"}"); goto finish_err; }
  {
    char buf[2048];
    while (true) {
      size_t n = fread(buf, 1, sizeof(buf)-1, fp);
      if (n == 0) break; buf[n] = 0; std::string chunk(buf);
      size_t start = 0, pos;
      while ((pos = chunk.find('\n', start)) != std::string::npos) {
        std::string line = chunk.substr(start, pos-start); start = pos+1;
        try {
          if (line.empty()) continue;
          auto j = nlohmann::json::parse(line);
          std::string tp = j.contains("type") && j["type"].is_string()? j["type"].get<std::string>() : std::string("");
          if (tp.empty()) continue;
          if (tp == "metrics") {
            nlohmann::json d = j["data"];
            train_emit(tj, "metrics", d.dump());
            try { controlplane::db::train_job_update(cfg, job_id, { {"metrics", d} }); } catch (...) {}
          } else if (tp == "artifact") {
            nlohmann::json d; d["path"] = j.value("path", "");
            train_emit(tj, "artifact", d.dump());
            {
              std::lock_guard<std::mutex> lk(tj->mu); tj->phase = "exporting"; tj->progress = 0.9;
            }
            train_emit(tj, "state", "{\"phase\":\"exporting\",\"progress\":0.9}");
          } else if (tp == "done") {
            std::string runid = j.value("run_id", std::string(""));
            try { controlplane::db::train_job_update(cfg, job_id, { {"status","done"}, {"phase","done"}, {"mlflow_run_id", runid} }); } catch (...) {}
            {
              std::lock_guard<std::mutex> lk(tj->mu); tj->status = "done"; tj->phase = "done"; tj->progress = 1.0; tj->done = true;
            }
            train_emit(tj, "done", std::string("{\"run_id\":\"") + runid + "\"}");
          } else if (tp == "error") {
            std::string msg = j.value("msg", std::string("trainer error"));
            try { controlplane::db::train_job_update(cfg, job_id, { {"status","failed"}, {"error", msg} }); } catch (...) {}
            train_emit(tj, "error", std::string("{\"msg\":\"") + msg + "\"}");
          }
        } catch (...) {
          // ignore
        }
      }
    }
    int rc = pclose(fp); (void)rc;
  }
  {
    std::lock_guard<std::mutex> lk(tj->mu);
    if (!tj->done) {
      tj->status = "done"; tj->phase = "done"; tj->progress = 1.0; tj->done = true;
      train_emit(tj, "done", "{\"phase\":\"done\"}");
      try { controlplane::db::train_job_update(cfg, job_id, { {"status","done"}, {"phase","done"} }); } catch (...) {}
    }
  }
  return;
finish_err:
  try { controlplane::db::train_job_update(cfg, job_id, { {"status","failed"}, {"error", "spawn_failed"} }); } catch (...) {}
  {
    std::lock_guard<std::mutex> lk(tj->mu); tj->status = "failed"; tj->phase = "failed"; tj->done = true;
  }
}

int main(int argc, char** argv) {
  using namespace controlplane;
  using nlohmann::json;
  std::string cfgDir = "controlplane/config";
  if (argc >= 2) cfgDir = argv[1];

  AppConfig cfg;
  std::string err;
  if (!load_config(cfgDir, &cfg, &err)) {
    std::cerr << "[controlplane] load_config failed: " << err << std::endl;
    return 1;
  }
  // Initialize gRPC TLS (if configured)
  try { controlplane::init_grpc_tls_from_config(cfg); } catch (...) {}
  std::cout << "[controlplane] listen=" << cfg.http_listen
            << " va=" << cfg.va_addr << " vsm=" << cfg.vsm_addr << std::endl;

  // Quick gRPC probes (best-effort)
  try { quick_probe_va(cfg.va_addr); } catch (...) {}
  try { quick_probe_vsm(cfg.vsm_addr); } catch (...) {}

  // Start HTTP server
  HttpServer http;
  auto handler = [cfg](const std::string& method, const std::string& path, const std::string& headers, const std::string& body) -> HttpResponse {
    HttpResponse r;
    auto t0 = std::chrono::steady_clock::now();
    auto emit = [&](const std::string& route, int code){
      using namespace std::chrono;
      auto dt = duration_cast<milliseconds>(steady_clock::now()-t0).count();
      try { controlplane::metrics::inc_request_with_ms(route, method, code, static_cast<double>(dt)); } catch (...) {}
    };
    // Debug echo: return observed path (for troubleshooting routing)
    if (path.rfind("/api/_debug/echo", 0) == 0) {
      nlohmann::json out;
      out["code"] = "OK";
      out["data"] = { {"path", path} };
      r.status = 200; r.body = out.dump(); emit("/api/_debug/echo", r.status); return r;
    }
    if (path.rfind("/api/_debug/sub/get", 0) == 0) {
      // parse id from query string: /api/_debug/sub/get?id=cp-...
      auto q = path.find('?'); std::string id;
      if (q != std::string::npos) {
        auto qs = path.substr(q+1);
        auto k = std::string("id="); auto p = qs.find(k);
        if (p != std::string::npos) { p += k.size(); auto e = qs.find('&', p); id = qs.substr(p, e==std::string::npos? std::string::npos : e-p); }
      }
      nlohmann::json out; out["code"] = "OK"; nlohmann::json d; d["id"] = id;
      auto rec = controlplane::Store::instance().get(id);
      d["found"] = (bool)rec.has_value();
      out["data"] = d; r.status = 200; r.body = out.dump(); emit("/api/_debug/sub/get", r.status); return r;
    }
    // Helpers: extract header value by key (case-sensitive minimal)
    auto get_header = [&](const std::string& key)->std::string{
      auto p = headers.find(key);
      if (p == std::string::npos) return {};
      p += key.size();
      auto e = headers.find("\r\n", p);
      auto v = headers.substr(p, e==std::string::npos? std::string::npos : e-p);
      size_t b=0; while (b<v.size() && (v[b]==' '||v[b]=='\t')) ++b; return v.substr(b);
    };
    auto origin = get_header("Origin:");
    auto authz  = get_header("Authorization:");
    auto req_id = get_header("X-Request-Id:");
    auto corr   = get_header("X-Correlation-Id:");
    auto make_id = [&](){
      auto now = std::chrono::duration_cast<std::chrono::microseconds>(std::chrono::steady_clock::now().time_since_epoch()).count();
      std::ostringstream os; os << std::hex << now; return os.str();
    };
    std::string corr_id = !corr.empty()? corr : (!req_id.empty()? req_id : make_id());
    auto origin_allowed = [&](){
      const auto& allow = cfg.security.cors_allowed_origins;
      if (allow.empty()) return true;
      if (allow.size()==1 && allow[0]=="*") return true;
      if (origin.empty()) return false;
      for (const auto& o : allow) if (o==origin) return true;
      return false;
    }();
    auto set_cors = [&](HttpResponse& rr){
      if (cfg.security.cors_allowed_origins.size()==1 && cfg.security.cors_allowed_origins[0]=="*") {
        rr.extraHeaders = "Access-Control-Allow-Origin: *\r\n";
      } else if (!origin.empty() && origin_allowed) {
        rr.extraHeaders = std::string("Access-Control-Allow-Origin: ") + origin + "\r\n";
      }
    };
    set_cors(r);
    // propagate correlation id
    if (!corr_id.empty()) {
      r.extraHeaders += std::string("X-Correlation-Id: ") + corr_id + "\r\n";
    }
    // CORS preflight
    if (method == "OPTIONS") {
      r.status = 200;
      // Allow common verbs and headers used by front-end/RTC flows
      r.extraHeaders += "Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, OPTIONS\r\n";
      r.extraHeaders += "Access-Control-Allow-Headers: Content-Type, Authorization, Accept, If-Match, Accept-Patch\r\n";
      r.extraHeaders += "Access-Control-Expose-Headers: Location, ETag, Accept-Patch\r\n";
      r.body = ""; emit("OPTIONS", r.status); return r;
    }
    // Security: bearer token (only when configured); exempt /metrics
    auto needs_auth = [&](){ return !cfg.security.bearer_token.empty() && path.rfind("/metrics",0)!=0; }();
    if (needs_auth) {
      bool ok=false;
      if (authz.rfind("Bearer ", 0) == 0) {
        auto tok = authz.substr(7);
        if (tok == cfg.security.bearer_token) ok = true;
      }
      if (!ok) { r.status=401; r.body="{\"code\":\"UNAUTHORIZED\"}"; set_cors(r); return r; }
    }
    // Per-route simple rate limit (best-effort)
    if (cfg.security.rate_limit_rps > 0) {
      struct Counter { int64_t sec; int count; };
      static std::mutex mu; static std::unordered_map<std::string, Counter> map;
      auto now = std::chrono::system_clock::now();
      auto sec = std::chrono::duration_cast<std::chrono::seconds>(now.time_since_epoch()).count();
      {
        std::lock_guard<std::mutex> lk(mu);
        auto& c = map[path];
        if (c.sec != sec) { c.sec = sec; c.count = 0; }
        c.count++;
        if (c.count > cfg.security.rate_limit_rps) { r.status=429; r.body="{\"code\":\"RATE_LIMIT\"}"; set_cors(r); return r; }
      }
    }
    if (path == "/api/system/info" && method == "GET") {
      // Aggregate from VA QueryRuntime and VSM GetHealth (best-effort)
      std::string provider = ""; bool gpu=false, iob=false; int vsm_streams = -1;
      // cache: 2s TTL
      {
        std::string cached;
        if (controlplane::cache::SimpleCache::instance().get("system_info", 2000, &cached)) {
          r.status = 200; r.body = cached; emit("/api/system/info", r.status); return r;
        }
      }
      try {
        auto stub = controlplane::make_va_stub(cfg.va_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        va::v1::QueryRuntimeRequest req; va::v1::QueryRuntimeReply rep; auto s = stub->QueryRuntime(&ctx, req, &rep);
        if (s.ok()) { provider=rep.provider(); gpu=rep.gpu_active(); iob=rep.io_binding(); }
      } catch (...) {}
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        vsm::v1::GetHealthRequest req; vsm::v1::GetHealthReply rep; auto s = stub->GetHealth(&ctx, req, &rep);
        if (s.ok()) { vsm_streams = rep.streams_size(); }
      } catch (...) {}
      std::ostringstream os;
      os << "{\"code\":\"OK\",\"data\":{";
      // CP restream config
      os << "\"restream\":{\"rtsp_base\":\"" << cfg.restream_rtsp_base << "\",\"source\":\"config\"},";
      // SFU/WHEP endpoint for negotiation: use cfg value; also echo default variant (cfg/env fallback)
      {
        std::string base = cfg.sfu_whep_base.empty()? std::string("http://") + cfg.http_listen : cfg.sfu_whep_base;
        std::string defv = cfg.sfu_whep_default_variant.empty()? "overlay" : cfg.sfu_whep_default_variant;
        if (defv.empty()) { try { const char* v = std::getenv("VA_WHEP_DEFAULT_VARIANT"); if (v && *v) defv = v; } catch (...) {} }
        for (auto& ch : defv) ch = (char)std::tolower((unsigned char)ch);
        std::string pause = cfg.sfu_pause_policy.empty()? "pass_through" : cfg.sfu_pause_policy;
        for (auto& ch : pause) ch = (char)std::tolower((unsigned char)ch);
        os << "\"sfu\":{\"whep_base\":\"" << base << "\",\"whep_default_variant\":\"" << defv << "\",\"pause_policy\":\"" << pause << "\"},";
      }
      // VA runtime
      os << "\"runtime\":{\"provider\":\""<<provider<<"\",\"gpu_active\":"<<(gpu?"true":"false")<<",\"io_binding\":"<<(iob?"true":"false")<<"},";
      // Subscriptions quotas (source: env or defaults)
      {
        auto envInt = [](const char* k, int defv){ const char* v = std::getenv(k); if (!v || !*v) return defv; try { return std::stoi(v); } catch (...) { return defv; } };
        auto srcOf = [](const char* k){ const char* v = std::getenv(k); return (v && *v) ? "env" : "defaults"; };
        int heavy = envInt("CP_SUBS_HEAVY_SLOTS", 2);
        int model = envInt("CP_SUBS_MODEL_SLOTS", 2);
        int rtsp  = envInt("CP_SUBS_RTSP_SLOTS", 4);
        int maxq  = envInt("CP_SUBS_MAX_QUEUE", 1024);
        int ttl   = envInt("CP_SUBS_TTL_SECONDS", 900);
        const char* s_heavy = srcOf("CP_SUBS_HEAVY_SLOTS");
        const char* s_model = srcOf("CP_SUBS_MODEL_SLOTS");
        const char* s_rtsp  = srcOf("CP_SUBS_RTSP_SLOTS");
        const char* s_maxq  = srcOf("CP_SUBS_MAX_QUEUE");
        const char* s_ttl   = srcOf("CP_SUBS_TTL_SECONDS");
        os << "\"subscriptions\":{"
              "\"heavy_slots\":" << heavy << ","
              "\"model_slots\":" << model << ","
              "\"rtsp_slots\":"  << rtsp  << ","
              "\"max_queue\":"    << maxq  << ","
              "\"ttl_seconds\":"  << ttl   << ","
              "\"source\":{"
                "\"heavy_slots\":\"" << s_heavy << "\","
                "\"model_slots\":\"" << s_model << "\","
                "\"rtsp_slots\":\""  << s_rtsp  << "\","
                "\"max_queue\":\""    << s_maxq  << "\","
                "\"ttl_seconds\":\""  << s_ttl   << "\"}"
            "},";
      }
      // VSM summary
      os << "\"vsm\":{\"streams\":"<<vsm_streams<<"}";
      os << "}}";
      r.status = 200; r.body = os.str();
      controlplane::cache::SimpleCache::instance().put("system_info", r.body);
      emit("/api/system/info", r.status);
      return r;
    }
    // Minimal list endpoints for front-end optional lists
    if (path == "/api/models" && method == "GET") {
      // Prefer VA gRPC RepoList (Triton repo); fallback to DB-based list when empty/unavailable
      try {
        std::vector<std::string> models; std::string err;
        if (va_repo_list(cfg.va_addr, &models, &err) && !models.empty()) {
          std::ostringstream os; os << "{\"code\":\"OK\",\"data\":[";
          for (size_t i=0;i<models.size();++i) { if (i) os << ","; os << "{\"id\":\""<<models[i]<<"\"}"; }
          os << "]}"; r.status=200; r.body=os.str(); emit("/api/models", r.status); return r;
        }
      } catch (...) { /* ignore and fallback */ }
      std::string arr;
      if (controlplane::db::list_models_json(cfg, &arr)) {
        r.status = 200; r.body = std::string("{\"code\":\"OK\",\"data\":") + arr + "}";
      } else {
        r.status = 200; r.body = "{\"code\":\"OK\",\"data\":[]}";
      }
      emit("/api/models", r.status); return r;
    }

    // --- Model aliases (M1) -------------------------------------------------
    static std::unordered_map<std::string, std::pair<std::string,std::string>> g_aliases; // alias -> {model_id, version}
    static bool g_aliases_loaded = false;
    auto aliases_file = []() -> std::string {
      const char* p = std::getenv("CP_ALIASES_FILE");
      if (p && *p) return std::string(p);
      return std::string("logs/model_aliases.json");
    };
    auto load_aliases = [&](){
      if (g_aliases_loaded) return; g_aliases_loaded = true;
      try {
        std::ifstream ifs(aliases_file()); if (!ifs.good()) return; nlohmann::json j; ifs >> j;
        if (j.is_array()) {
          for (auto& it : j) {
            std::string alias = it.value("alias", ""); std::string model_id = it.value("model_id", ""); std::string version = it.value("version", "");
            if (!alias.empty() && !model_id.empty()) g_aliases[alias] = {model_id, version};
          }
        }
      } catch (...) { /* ignore */ }
    };
    auto save_aliases = [&](){
      try {
        nlohmann::json arr = nlohmann::json::array();
        for (const auto& kv : g_aliases) {
          nlohmann::json o; o["alias"] = kv.first; o["model_id"] = kv.second.first; if (!kv.second.second.empty()) o["version"] = kv.second.second; arr.push_back(o);
        }
        std::filesystem::create_directories("logs");
        std::ofstream ofs(aliases_file()); if (!ofs.good()) return; ofs << arr.dump();
      } catch (...) { /* ignore */ }
    };

    if (path == "/api/models/aliases" && method == "GET") {
      load_aliases();
      nlohmann::json arr = nlohmann::json::array();
      for (const auto& kv : g_aliases) { nlohmann::json o; o["alias"]=kv.first; o["model_id"]=kv.second.first; if(!kv.second.second.empty()) o["version"]=kv.second.second; arr.push_back(o); }
      nlohmann::json out; out["code"]="OK"; out["data"]=arr; r.status=200; r.body=out.dump(); emit("/api/models/aliases", r.status); return r;
    }
    if (path == "/api/models/aliases" && method == "POST") {
      load_aliases();
      try {
        auto j = nlohmann::json::parse(body);
        std::string alias = j.value("alias", ""); std::string model_id = j.value("model_id", ""); std::string version = j.value("version", "");
        if (alias.empty() || model_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/models/aliases", r.status); return r; }
        g_aliases[alias] = {model_id, version}; save_aliases();
        r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/models/aliases", r.status); return r;
      } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/models/aliases", r.status); return r; }
    }
    if (path.rfind("/api/models/aliases/", 0) == 0 && method == "DELETE") {
      load_aliases();
      auto alias = path.substr(std::string("/api/models/aliases/").size());
      auto it = g_aliases.find(alias);
      if (it != g_aliases.end()) { g_aliases.erase(it); save_aliases(); }
      r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/models/aliases/{alias}", r.status); return r;
    }
    if (path == "/api/pipelines" && method == "GET") {
      std::string arr;
      if (controlplane::db::list_pipelines_json(cfg, &arr)) {
        r.status = 200; r.body = std::string("{\"code\":\"OK\",\"data\":") + arr + "}";
      } else {
        r.status = 200; r.body = "{\"code\":\"OK\",\"data\":[]}";
      }
      emit("/api/pipelines", r.status); return r;
    }
    if (path == "/api/graphs" && method == "GET") {
      std::string arr;
      if (controlplane::db::list_graphs_json(cfg, &arr)) {
        r.status = 200; r.body = std::string("{\"code\":\"OK\",\"data\":") + arr + "}";
      } else {
        r.status = 200; r.body = "{\"code\":\"OK\",\"data\":[]}";
      }
      emit("/api/graphs", r.status); return r;
    }
    if (path == "/api/_debug/db" && method == "GET") {
      nlohmann::json j; controlplane::db::db_error_snapshot(&j);
      nlohmann::json info;
      info["driver"] = cfg.db.driver;
      info["mysqlx_uri"] = cfg.db.mysqlx_uri;
      info["host"] = cfg.db.host;
      info["port"] = cfg.db.port;
      info["user"] = cfg.db.user;
      info["schema"] = cfg.db.schema;
      nlohmann::json out;
      out["code"] = "OK";
      out["data"] = { {"errors", j}, {"cfg", info} };
      r.status = 200; r.body = out.dump(); emit("/api/_debug/db", r.status); return r;
    }
    // Fast-path: resource GET /api/subscriptions/{id}[?include=...]
    if (method == "GET" && path.rfind("/api/subscriptions/", 0) == 0 && path.find("/events") == std::string::npos) {
      std::string raw_path = path;
      auto qmark = raw_path.find('?');
      const std::string prefix = "/api/subscriptions/";
      size_t start = prefix.size();
      size_t end = (qmark==std::string::npos) ? raw_path.size() : qmark;
      if (start >= end) { r.status = 404; r.body = "{}"; emit("/api/subscriptions/{id}", r.status); return r; }
      auto cp_id = raw_path.substr(start, end - start);
      // Truncate if encoded '?' is present in path (e.g. "%3Finclude=...")
      {
        std::string low = cp_id; for (auto& c : low) c = (char)std::tolower((unsigned char)c);
        auto p3f = low.find("%3f"); if (p3f != std::string::npos) cp_id = cp_id.substr(0, p3f);
      }
      auto rec = Store::instance().get(cp_id);
      if (!rec) { r.status = 404; r.body = "{\"code\":\"NOT_FOUND\"}"; emit("/api/subscriptions/{id}", r.status); return r; }
      auto etag = Store::make_etag(*rec);
      r.extraHeaders += std::string("ETag: ") + etag + "\r\nAccess-Control-Expose-Headers: ETag,Location\r\n";
      // phase (best-effort refresh from VA)
      std::string phase = rec->last.phase;
      std::string reason = rec->last.reason;
      try {
        if (!rec->va_subscription_id.empty()) {
          auto stub = controlplane::make_va_stub(cfg.va_addr);
          grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
          va::v1::ListPipelinesRequest preq; va::v1::ListPipelinesReply prep;
          auto s = stub->ListPipelines(&ctx, preq, &prep);
          if (s.ok()) {
            for (const auto& it : prep.items()) {
              if (it.key() == rec->va_subscription_id) { if (it.running()) { phase = "ready"; reason.clear(); } break; }
            }
          }
        }
      } catch (...) {}
      bool want_timeline = false;
      if (qmark != std::string::npos) { auto qs = raw_path.substr(qmark+1); if (qs.find("include=timeline") != std::string::npos) want_timeline = true; }
      nlohmann::json data;
      data["id"] = rec->cp_id;
      data["phase"] = phase;
      if (!reason.empty()) data["reason"] = reason;
      data["created_at"] = rec->last.ts_ms;
      data["pipeline_key"] = rec->va_subscription_id;
      if (want_timeline) {
        nlohmann::json t; t["phase"] = rec->last.phase; t["ts_ms"] = rec->last.ts_ms; if (!rec->last.reason.empty()) t["reason"] = rec->last.reason; data["timeline"] = nlohmann::json::array({t});
      }
      nlohmann::json out; out["code"] = "OK"; out["data"] = data;
      r.status = 200; r.body = out.dump(); emit("/api/subscriptions/{id}", r.status); return r;
    }
    if (path == "/api/_metrics/summary" && method == "GET") {
      nlohmann::json out; out["code"] = "OK";
      out["data"] = nlohmann::json::object();
      try {
        auto s = controlplane::metrics::render_json_summary();
        out["data"]["cp"] = nlohmann::json::parse(s);
      } catch (...) { out["data"]["cp"] = { {"error","metrics_summary_failed"} }; }
      try {
        auto st = controlplane::cache::SimpleCache::stats();
        out["data"]["cache"] = { {"hits", st.hits}, {"misses", st.misses} };
      } catch (...) { out["data"]["cache"] = { {"error","cache_stats_failed"} }; }
      r.status = 200; r.body = out.dump(); emit("/api/_metrics/summary", r.status); return r;
    }
    // Minimal events recent endpoint for front-end compatibility
    if (path.rfind("/api/events/recent", 0) == 0 && method == "GET") {
      nlohmann::json out; out["code"] = "OK";
      // return empty list with paging fields for compatibility
      nlohmann::json data; data["items"] = nlohmann::json::array(); data["next"] = 0;
      out["data"] = data;
      r.status = 200; r.body = out.dump(); emit("/api/events/recent", r.status); return r;
    }
    // Training: start
    if (path == "/api/train/start" && method == "POST") {
      try {
        nlohmann::json cfgj = body.empty()? nlohmann::json::object() : nlohmann::json::parse(body);
        std::string job = gen_train_job_id();
        auto rec = std::make_shared<TrainJobRec>();
        {
          std::lock_guard<std::mutex> lk(g_train_mu); g_train_jobs[job] = rec;
        }
        const char* tcmd = std::getenv("CP_TRAINER_CMD");
        if (tcmd && *tcmd) {
          std::thread([cfg, job, cfgj]{ launch_trainer_subprocess(cfg, job, cfgj); }).detach();
        } else {
          std::thread([cfg, job, cfgj]{ launch_train_simulator(cfg, job, cfgj); }).detach();
        }
        nlohmann::json out; out["code"]="ACCEPTED"; out["data"]={{"job",job},{"events","/api/train/events?id="+job}};
        r.status=202; r.body=out.dump(); emit("/api/train/start", r.status); return r;
      } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/train/start", r.status); return r; }
    }
    // Training: status
    if (path.rfind("/api/train/status", 0) == 0 && method == "GET") {
      auto qpos = path.find('?'); std::string qs = (qpos==std::string::npos)? std::string("") : path.substr(qpos+1);
      auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
      std::string id = getq("id");
      std::shared_ptr<TrainJobRec> tj;
      { std::lock_guard<std::mutex> lk(g_train_mu); auto it=g_train_jobs.find(id); if(it!=g_train_jobs.end()) tj=it->second; }
      nlohmann::json out; out["code"] = "OK"; nlohmann::json d;
      if (tj) { std::lock_guard<std::mutex> lk(tj->mu); d["id"]=id; d["status"]=tj->status; d["phase"]=tj->phase; d["progress"]=tj->progress; }
      else { std::string sjson; if (controlplane::db::train_job_get_json(cfg, id, &sjson)) { try { d = nlohmann::json::parse(sjson); } catch (...) { d = nlohmann::json::object(); } } }
      out["data"]=d; r.status=200; r.body=out.dump(); emit("/api/train/status", r.status); return r;
    }
    // Training: list (summary)
    if (path == "/api/train/list" && method == "GET") {
      std::string sjson; controlplane::db::list_train_jobs_json(cfg, &sjson);
      nlohmann::json out; out["code"]="OK"; try { out["data"]=nlohmann::json::parse(sjson); } catch (...) { out["data"]=nlohmann::json::array(); }
      r.status=200; r.body=out.dump(); emit("/api/train/list", r.status); return r;
    }
    if (path == "/api/va/runtime" && method == "GET") {
      nlohmann::json out; out["code"] = "OK";
      try {
        auto stub = controlplane::make_va_stub(cfg.va_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        va::v1::QueryRuntimeRequest req; va::v1::QueryRuntimeReply rep;
        auto s = stub->QueryRuntime(&ctx, req, &rep);
        if (s.ok()) {
          out["data"] = { {"provider", rep.provider()}, {"gpu_active", rep.gpu_active()}, {"io_binding", rep.io_binding()}, {"device_binding", rep.device_binding()} };
          r.status = 200; r.body = out.dump(); emit("/api/va/runtime", r.status); return r;
        } else {
          out["code"] = "BACKEND_ERROR"; out["msg"] = s.error_message(); r.status = 502; r.body = out.dump(); emit("/api/va/runtime", r.status); return r;
        }
      } catch (const std::exception& ex) {
        out["code"]="EXCEPTION"; out["msg"]=ex.what(); r.status=500; r.body=out.dump(); emit("/api/va/runtime", r.status); return r;
      } catch (...) {
        out["code"]="EXCEPTION"; out["msg"]="unknown"; r.status=500; r.body=out.dump(); emit("/api/va/runtime", r.status); return r;
      }
    }
    if (path == "/api/ui/schema/engine" && method == "GET") {
      nlohmann::json j;
      j["title"] = "EngineOptionsSchema";
      j["version"] = 1;
      nlohmann::json fields = nlohmann::json::array();
      auto add = [&](const char* key, const char* type, const char* defv, const char* help, nlohmann::json extra = nlohmann::json::object()){
        nlohmann::json f; f["key"]=key; f["type"]=type; if(defv&&*defv) f["default"]=defv; if(help&&*help) f["help"]=help; for(auto it=extra.begin(); it!=extra.end(); ++it){ f[it.key()] = it.value(); } fields.push_back(f);
      };
      // Core
      add("provider", "enum", "triton", "推理提供方", { {"enum", nlohmann::json::array({"tensorrt","cuda","cpu","triton"}) } });
      add("device", "int", "0", "GPU 设备号（若适用）");
      add("warmup_runs", "string", "auto", "预热次数（auto/-1=1 次；0=禁用；或整数）");
      // Triton connectivity
      add("triton_inproc", "bool", "true", "启用 In-Process Triton 嵌入");
      add("triton_repo", "string", "s3://http://minio:9000/cv-models/models", "模型仓库 URL（支持 MinIO）");
      add("triton_model", "string", "ens_det_trt_full", "模型名称（可为 Ensemble）");
      add("triton_model_version", "string", "", "模型版本（空=latest）");
      add("triton_enable_grpc", "bool", "false", "暴露 gRPC 端口（便于 perf_analyzer）");
      add("triton_enable_http", "bool", "false", "暴露 HTTP 端口（便于 perf_analyzer）");
      // Triton ServerOptions
      add("triton_backend_dir", "string", "", "后端目录（留空走默认/环境）");
      add("triton_pinned_mem_mb", "int", "256", "Pinned 内存池大小（MB）");
      add("triton_cuda_pool_device_id", "int", "0", "CUDA 内存池设备号");
      add("triton_cuda_pool_bytes", "string", "268435456", "CUDA 内存池字节数（字符串避免溢出）");
      add("triton_backend_configs", "string", "tensorrt:coalesce_request_input=1", "后端参数，分号分隔，如 backend:key=value");
      // IO
      add("triton_gpu_input", "bool", "true", "输入走 GPU 直通（In-Process）");
      add("triton_gpu_output", "bool", "true", "输出走 GPU 直通（In-Process）");
      // Output schema
      j["fields"] = fields;
      nlohmann::json out; out["code"]="OK"; out["data"]=j;
      r.status = 200; r.body = out.dump(); emit("/api/ui/schema/engine", r.status); return r;
    }
    if (path == "/api/control/set_engine" && method == "POST") {
      std::string provider; int device=0; std::unordered_map<std::string,std::string> options;
      if (!body.empty()) {
        try {
          nlohmann::json j = nlohmann::json::parse(body);
          if (j.contains("provider") && j["provider"].is_string()) provider = j["provider"].get<std::string>();
          if (j.contains("device") && j["device"].is_number_integer()) device = j["device"].get<int>();
          if (j.contains("options") && j["options"].is_object()) {
            for (auto it = j["options"].begin(); it != j["options"].end(); ++it) { options[it.key()] = it.value().is_string()? it.value().get<std::string>() : it.value().dump(); }
          } else {
            // 扁平键值（容错）：将非保留字段视为 options
            for (auto it = j.begin(); it != j.end(); ++it) {
              const std::string k = it.key(); if (k=="provider"||k=="device") continue; options[k] = it.value().is_string()? it.value().get<std::string>() : it.value().dump();
            }
          }
        } catch (...) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/set_engine", r.status); return r; }
      }
      try {
        auto stub = controlplane::make_va_stub(cfg.va_addr);
        va::v1::SetEngineRequest req; va::v1::SetEngineReply rep; grpc::ClientContext ctx;
        if (!provider.empty()) req.set_provider(provider);
        if (device != 0) req.set_device(device);
        for (const auto& kv : options) (*req.mutable_options())[kv.first] = kv.second;
        auto s = stub->SetEngine(&ctx, req, &rep);
        if (!s.ok() || !rep.ok()) { auto mm=cp_map_err(s.error_message()); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(s.ok()? rep.msg(): s.error_message())+"\"}"; emit("/api/control/set_engine", r.status); return r; }
        nlohmann::json out; out["code"]="OK"; out["data"]={ {"provider", rep.provider()}, {"gpu_active", rep.gpu_active()}, {"io_binding", rep.io_binding()}, {"device_binding", rep.device_binding()} };
        r.status=200; r.body = out.dump(); emit("/api/control/set_engine", r.status); return r;
      } catch (const std::exception& ex) { r.status=500; r.body=std::string("{\"code\":\"INTERNAL\",\"msg\":\"")+ex.what()+"\"}"; emit("/api/control/set_engine", r.status); return r; }
    }
    if (path == "/api/repo/load" && method == "POST") {
      std::string model; if (!body.empty()) { try { auto j=nlohmann::json::parse(body); if (j.contains("model")&&j["model"].is_string()) model=j["model"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/load", r.status); return r; } }
      if (model.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/repo/load", r.status); return r; }
      // manifest pre-check: fetch model.yaml and validate before loading
      {
        std::string mcontent; std::string merr;
        if (!controlplane::va_repo_get_config(cfg.va_addr, model, &mcontent, &merr) || mcontent.empty()) {
          r.status=422; r.body = std::string("{\"code\":\"UNPROCESSABLE_ENTITY\",\"detail\":{\"code\":\"MANIFEST_REQUIRED\",\"msg\":\"model.yaml missing or fetch failed: ") + (merr.empty()? std::string("not found"): merr) + "\"}}"; emit("/api/repo/load", r.status); return r; }
        auto chk = controlplane::manifest::validate_yaml(mcontent);
        if (!chk.ok) { nlohmann::json out; out["code"]="UNPROCESSABLE_ENTITY"; out["detail"]={{"code",chk.code},{"msg",chk.msg}}; if(!chk.diag.is_null()) out["detail"]["diag"]=chk.diag; r.status=422; r.body = out.dump(); emit("/api/repo/load", r.status); return r; }
      }
      std::string err; bool ok = va_repo_load(cfg.va_addr, model, &err);
      if (!ok) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err+"\"}"; emit("/api/repo/load", r.status); try{ controlplane::metrics::inc_repo_op("load", false);}catch(...){} return r; }
      try{ controlplane::metrics::inc_repo_op("load", true);}catch(...){}
      r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/load", r.status); return r;
    }
    if (path == "/api/repo/unload" && method == "POST") {
      std::string model; if (!body.empty()) { try { auto j=nlohmann::json::parse(body); if (j.contains("model")&&j["model"].is_string()) model=j["model"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/unload", r.status); return r; } }
      if (model.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/repo/unload", r.status); return r; }
      std::string err; bool ok = va_repo_unload(cfg.va_addr, model, &err);
      if (!ok) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err+"\"}"; emit("/api/repo/unload", r.status); try{ controlplane::metrics::inc_repo_op("unload", false);}catch(...){} return r; }
      try{ controlplane::metrics::inc_repo_op("unload", true);}catch(...){}
      r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/unload", r.status); return r;
    }
    if (path == "/api/repo/poll" && method == "POST") {
      std::string err; bool ok = va_repo_poll(cfg.va_addr, &err);
      if (!ok) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err+"\"}"; emit("/api/repo/poll", r.status); try{ controlplane::metrics::inc_repo_op("poll", false);}catch(...){} return r; }
      try{ controlplane::metrics::inc_repo_op("poll", true);}catch(...){}
      r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/poll", r.status); return r;
    }
    if (path == "/api/repo/remove" && method == "POST") {
      std::string model;
      if (!body.empty()) {
        try { auto j=nlohmann::json::parse(body); if (j.contains("model") && j["model"].is_string()) model = j["model"].get<std::string>(); }
        catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/remove", r.status); return r; }
      }
      if (model.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/repo/remove", r.status); return r; }
      // best-effort unload first
      try { std::string err; va_repo_unload(cfg.va_addr, model, &err); } catch (...) {}
      std::string err;
      bool ok = controlplane::va_repo_remove_model(cfg.va_addr, model, &err);
      if (!ok) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err+"\"}"; emit("/api/repo/remove", r.status); try{ controlplane::metrics::inc_repo_op("remove", false);}catch(...){} return r; }
      r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/remove", r.status); try{ controlplane::metrics::inc_repo_op("remove", true);}catch(...){} return r;
    }
    if (path.rfind("/api/repo/upload", 0) == 0 && method == "POST") {
      auto qpos = path.find('?');
      std::string qs = (qpos==std::string::npos)? std::string("") : path.substr(qpos+1);
      auto url_decode = [&](const std::string& s){ std::string out; out.reserve(s.size()); for (size_t i=0;i<s.size();++i){ char c=s[i]; if (c=='+'){ out.push_back(' '); continue; } if (c=='%' && i+2<s.size()){ auto hex=[&](char x){ if (x>='0'&&x<='9') return x-'0'; if (x>='a'&&x<='f') return 10+(x-'a'); if (x>='A'&&x<='F') return 10+(x-'A'); return 0; }; out.push_back(static_cast<char>((hex(s[i+1])<<4)|hex(s[i+2]))); i+=2; } else out.push_back(c);} return out; };
      auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return url_decode(qs.substr(p, e==std::string::npos? std::string::npos : e-p)); };
      std::string model = getq("model");
      std::string version = getq("version"); if (version.empty()) version = "1";
      std::string filename = getq("filename");
      auto ctype = get_header("Content-Type:");
      std::string content; content.assign(body.begin(), body.end());
      if (!(ctype.find("application/octet-stream") != std::string::npos)) {
        try {
          auto j = nlohmann::json::parse(body);
          if (model.empty() && j.contains("model")) model = j["model"].get<std::string>();
          if (version=="1" && j.contains("version") && j["version"].is_string()) version = j["version"].get<std::string>();
          if (filename.empty() && j.contains("filename")) filename = j["filename"].get<std::string>();
          auto b64 = j.contains("content_b64") ? j["content_b64"].get<std::string>() : std::string("");
          if (!b64.empty()) {
            auto decode = [](const std::string& s){
              int T[256]; for (int i=0;i<256;++i) T[i] = -1;
              for (int i=0;i<26;++i){ T['A'+i]=i; T['a'+i]=26+i; }
              for (int i=0;i<10;++i){ T['0'+i]=52+i; }
              T[(int)'+']=62; T[(int)'/']=63;
              std::string out; out.reserve(s.size()*3/4);
              int val=0, valb=-8; for (unsigned char c: s){ if(T[c]==-1){ if(c=='=') break; else continue; } val=(val<<6)+T[c]; valb+=6; if(valb>=0){ out.push_back(char((val>>valb)&0xFF)); valb-=8; } }
              return out;
            };
            content = decode(b64);
          }
        } catch (...) { /* ignore */ }
      }
      if (model.empty() || filename.empty()) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model/filename required\"}"; emit("/api/repo/upload", r.status); return r; }
      // If uploading manifest (model.yaml), validate before forwarding to VA
      {
        std::string fn = filename; for (auto& c : fn) c = (char)tolower((unsigned char)c);
        if (fn == "model.yaml" || fn == "/model.yaml" || fn.rfind("/model.yaml") != std::string::npos) {
          auto chk = controlplane::manifest::validate_yaml(content);
          if (!chk.ok) { nlohmann::json out; out["code"]="UNPROCESSABLE_ENTITY"; out["detail"]={{"code",chk.code},{"msg",chk.msg}}; if(!chk.diag.is_null()) out["detail"]["diag"]=chk.diag; r.status=422; r.body = out.dump(); emit("/api/repo/upload", r.status); return r; }
        }
      }
      std::string err; bool ok = controlplane::va_repo_put_file(cfg.va_addr, model, version, filename, content, &err);
      if (!ok) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(err.empty()? std::string("upload failed"): err)+"\"}"; emit("/api/repo/upload", r.status); return r; }
      nlohmann::json out; out["code"]="CREATED"; out["data"]={{"model",model},{"version",version},{"filename",filename}};
      r.status=201; r.body = out.dump(); emit("/api/repo/upload", r.status); return r;
    }
    // Convert ONNX -> TensorRT plan (on VA) : POST /api/repo/convert_upload?model=..&version=.. (body=onnx)
    if (path.rfind("/api/repo/convert_upload", 0) == 0 && method == "POST") {
      auto qpos = path.find('?');
      std::string qs = (qpos==std::string::npos)? std::string("") : path.substr(qpos+1);
      auto url_decode = [&](const std::string& s){ std::string out; out.reserve(s.size()); for (size_t i=0;i<s.size();++i){ char c=s[i]; if (c=='+'){ out.push_back(' '); continue; } if (c=='%' && i+2<s.size()){ auto hex=[&](char x){ if (x>='0'&&x<='9') return x-'0'; if (x>='a'&&x<='f') return 10+(x-'a'); if (x>='A'&&x<='F') return 10+(x-'A'); return 0; }; out.push_back(static_cast<char>((hex(s[i+1])<<4)|hex(s[i+2]))); i+=2; } else out.push_back(c);} return out; };
      auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return url_decode(qs.substr(p, e==std::string::npos? std::string::npos : e-p)); };
      std::string model = getq("model"); std::string version = getq("version"); if (version.empty()) version = "1";
      if (model.empty()) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model required\"}"; emit("/api/repo/convert_upload", r.status); return r; }
      if (body.empty()) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"ONNX bytes required in request body (Content-Type: application/octet-stream)\"}"; emit("/api/repo/convert_upload", r.status); return r; }
      // manifest pre-check
      {
        std::string mcontent; std::string merr;
        if (!controlplane::va_repo_get_config(cfg.va_addr, model, &mcontent, &merr) || mcontent.empty()) {
          r.status=422; r.body = std::string("{\"code\":\"UNPROCESSABLE_ENTITY\",\"detail\":{\"code\":\"MANIFEST_REQUIRED\",\"msg\":\"model.yaml missing or fetch failed: ") + (merr.empty()? std::string("not found"): merr) + "\"}}"; emit("/api/repo/convert_upload", r.status); return r; }
        auto chk = controlplane::manifest::validate_yaml(mcontent);
        if (!chk.ok) { nlohmann::json out; out["code"]="UNPROCESSABLE_ENTITY"; out["detail"]={{"code",chk.code},{"msg",chk.msg}}; if(!chk.diag.is_null()) out["detail"]["diag"]=chk.diag; r.status=422; r.body = out.dump(); emit("/api/repo/convert_upload", r.status); return r; }
      }
      std::string job; std::string err;
      if (!controlplane::va_repo_convert_upload(cfg.va_addr, model, version, body, &job, &err)) {
        auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(err.empty()? std::string("convert_upload failed"): err)+"\"}"; emit("/api/repo/convert_upload", r.status); return r; }
      nlohmann::json out; out["code"]="ACCEPTED"; out["data"]={{"job",job},{"events","/api/repo/convert/events?job="+job}};
      r.status=202; r.body=out.dump(); emit("/api/repo/convert_upload", r.status); return r;
    }
    if (path == "/api/repo/convert/cancel" && method == "POST") {
      try {
        std::string job;
        if (!body.empty()) { auto j = nlohmann::json::parse(body); if (j.contains("job") && j["job"].is_string()) job = j["job"].get<std::string>(); }
        if (job.empty()) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"job required\"}"; emit("/api/repo/convert/cancel", r.status); return r; }
        std::string err;
        if (!controlplane::va_repo_convert_cancel(cfg.va_addr, job, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(err.empty()? std::string("cancel failed"): err)+"\"}"; emit("/api/repo/convert/cancel", r.status); return r; }
        r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/convert/cancel", r.status); return r;
      } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/convert/cancel", r.status); return r; }
    }
    // Add a new model to Triton repository by creating config.pbtxt (minimal skeleton). Optionally load immediately.
    if (path == "/api/repo/add" && method == "POST") {
      try {
        std::string model; std::string content; bool autoload = false;
        if (!body.empty()) {
          auto j = nlohmann::json::parse(body);
          if (j.contains("model") && j["model"].is_string()) model = j["model"].get<std::string>();
          if (j.contains("config") && j["config"].is_string()) content = j["config"].get<std::string>();
          if (j.contains("load") && (j["load"].is_boolean() || j["load"].is_number())) autoload = j["load"].get<bool>();
        }
        if (model.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model required\"}"; emit("/api/repo/add", r.status); return r; }
        // If config is empty, generate a minimal skeleton with name only. Users can edit later.
        if (content.empty()) {
          std::ostringstream os; os << "name: \"" << model << "\"\n"; content = os.str();
        }
        std::string err;
        if (!va_repo_save_config(cfg.va_addr, model, content, &err)) {
          auto mm = cp_map_err(err);
          r.status = mm.code; r.body = std::string("{\"code\":\"") + mm.text + "\",\"msg\":\"" + (err.empty()? std::string("save failed"): err) + "\"}";
          emit("/api/repo/add", r.status); return r;
        }
        if (autoload) {
          std::string e2; (void)va_repo_load(cfg.va_addr, model, &e2); // best-effort; ignore failure here
        }
        nlohmann::json out; out["code"] = "CREATED"; nlohmann::json d; d["id"] = model; d["loaded"] = autoload; out["data"] = d;
        r.status = 201; r.body = out.dump(); emit("/api/repo/add", r.status); return r;
      } catch (...) {
        r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/add", r.status); return r;
      }
    }
    // List repo models via gRPC RepoList（尽量返回详细字段）
    if (path == "/api/repo/list" && method == "GET") {
      try {
        std::string err;
        std::vector<controlplane::RepoModelInfo> detail;
        if (va_repo_list_detail(cfg.va_addr, &detail, &err) && !detail.empty()) {
          std::ostringstream os; os << "{\"code\":\"OK\",\"data\":[";
          for (size_t i=0;i<detail.size();++i) {
            if (i) os << ",";
            os << "{\"id\":\""<<detail[i].id<<"\"";
            if (!detail[i].path.empty()) os << ",\"path\":\""<<detail[i].path<<"\"";
            os << ",\"ready\":" << (detail[i].ready? "true":"false");
            if (!detail[i].versions.empty()) {
              os << ",\"versions\":[";
              for (size_t j=0;j<detail[i].versions.size();++j) { if (j) os << ","; os << "\""<<detail[i].versions[j]<<"\""; }
              os << "]";
            }
            if (!detail[i].active_version.empty()) os << ",\"active_version\":\""<<detail[i].active_version<<"\"";
            os << "}";
          }
          os << "]}"; r.status=200; r.body=os.str(); emit("/api/repo/list", r.status); try{ controlplane::metrics::inc_repo_op("list", true);}catch(...){} return r;
        }
        // fallback: id only
        std::vector<std::string> models;
        if (!va_repo_list(cfg.va_addr, &models, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err+"\"}"; emit("/api/repo/list", r.status); try{ controlplane::metrics::inc_repo_op("list", false);}catch(...){} return r; }
        std::ostringstream os; os << "{\"code\":\"OK\",\"data\":[";
        for (size_t i=0;i<models.size();++i) { if (i) os << ","; os << "{\"id\":\""<<models[i]<<"\"}"; }
        os << "]}"; r.status=200; r.body=os.str(); emit("/api/repo/list", r.status); try{ controlplane::metrics::inc_repo_op("list", true);}catch(...){} return r;
      } catch (...) { r.status=500; r.body="{\"code\":\"INTERNAL\"}"; emit("/api/repo/list", r.status); return r; }
    }
    if (path.rfind("/api/repo/config", 0) == 0 && method == "GET") {
      try {
        // allow query ?model=xxx
        auto qpos = path.find('?'); std::string model;
        if (qpos != std::string::npos) {
          auto qs = path.substr(qpos+1);
          auto p = qs.find("model="); if (p != std::string::npos) {
            p += 6; auto e = qs.find('&', p); model = qs.substr(p, e==std::string::npos? std::string::npos : e-p);
          }
        }
        if (model.empty()) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model required\"}"; emit("/api/repo/config", r.status); return r; }
        // URL decode %xx
        auto url_decode = [](const std::string& s){ std::string o; o.reserve(s.size()); for(size_t i=0;i<s.size();++i){ char c=s[i]; if(c=='%' && i+2<s.size()){ char h1=s[i+1], h2=s[i+2]; auto hex=[&](char x){ if(x>='0'&&x<='9') return x-'0'; if(x>='a'&&x<='f') return 10+(x-'a'); if(x>='A'&&x<='F') return 10+(x-'A'); return 0; }; o.push_back((char)((hex(h1)<<4)|hex(h2))); i+=2; } else if(c=='+') o.push_back(' '); else o.push_back(c);} return o; };
        model = url_decode(model);
        std::string err, content;
        if (!va_repo_get_config(cfg.va_addr, model, &content, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(err.empty()?std::string("repo get config failed"):err)+"\"}"; emit("/api/repo/config", r.status); return r; }
        nlohmann::json out; out["code"]="OK"; nlohmann::json data; data["model"]=model; data["content"]=content; out["data"]=data;
        r.status=200; r.body=out.dump(); emit("/api/repo/config", r.status); return r;
      } catch (...) { r.status=500; r.body="{\"code\":\"INTERNAL\"}"; emit("/api/repo/config", r.status); return r; }
    }
    if (path == "/api/repo/config" && method == "POST") {
      try {
        std::string model, content;
        auto j = nlohmann::json::parse(body);
        if (j.contains("model") && j["model"].is_string()) model = j["model"].get<std::string>();
        if (j.contains("content") && j["content"].is_string()) content = j["content"].get<std::string>();
        if (model.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model required\"}"; emit("/api/repo/config", r.status); return r; }
        std::string err;
        if (!va_repo_save_config(cfg.va_addr, model, content, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(err.empty()?std::string("save failed"):err)+"\"}"; emit("/api/repo/config", r.status); return r; }
        r.status=200; r.body="{\"code\":\"OK\"}"; emit("/api/repo/config", r.status); return r;
      } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/repo/config", r.status); return r; }
    }
    if (path == "/api/control/release" && method == "POST") {
      std::string pipeline_name, node, triton_model, triton_version, model_uri, alias;
      if (!body.empty()) {
        try {
          nlohmann::json j = nlohmann::json::parse(body);
          if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>();
          if (j.contains("node")&&j["node"].is_string()) node=j["node"].get<std::string>();
          if (j.contains("triton_model")&&j["triton_model"].is_string()) triton_model=j["triton_model"].get<std::string>();
          if (j.contains("triton_model_version")&&j["triton_model_version"].is_string()) triton_version=j["triton_model_version"].get<std::string>();
          if (j.contains("model_uri")&&j["model_uri"].is_string()) model_uri=j["model_uri"].get<std::string>();
          if (j.contains("alias")&&j["alias"].is_string()) alias=j["alias"].get<std::string>();
        } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/release", r.status); return r; }
      }
      if (pipeline_name.empty() || node.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/release", r.status); return r; }
      try {
        // Resolve alias → triton_model[/version] if provided
        if (!alias.empty()) {
          try {
            load_aliases();
            auto it = g_aliases.find(alias);
            if (it != g_aliases.end()) {
              if (triton_model.empty()) triton_model = it->second.first;
              if (triton_version.empty()) triton_version = it->second.second;
            }
          } catch (...) { /* ignore */ }
        }
        auto stub = controlplane::make_va_stub(cfg.va_addr);
        if (!triton_model.empty()) {
          va::v1::SetEngineRequest sreq; va::v1::SetEngineReply srep; grpc::ClientContext sctx;
          (*sreq.mutable_options())["triton_model"] = triton_model;
          if (!triton_version.empty()) (*sreq.mutable_options())["triton_model_version"] = triton_version;
          auto st = stub->SetEngine(&sctx, sreq, &srep);
          if (!st.ok() || !srep.ok()) { auto mm=cp_map_err(st.error_message()); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(st.ok()? srep.msg(): st.error_message())+"\"}"; emit("/api/control/release", r.status); return r; }
          std::string errh; if (!va_hotswap_model(cfg.va_addr, pipeline_name, node, "__triton__", &errh)) { auto mm=cp_map_err(errh); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errh+"\"}"; emit("/api/control/release", r.status); return r; }
        } else {
          if (model_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"model_uri required\"}"; emit("/api/control/release", r.status); return r; }
          std::string errh; if (!va_hotswap_model(cfg.va_addr, pipeline_name, node, model_uri, &errh)) { auto mm=cp_map_err(errh); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errh+"\"}"; emit("/api/control/release", r.status); return r; }
        }
        r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/control/release", r.status); return r;
      } catch (const std::exception& ex) { r.status=500; r.body=std::string("{\"code\":\"INTERNAL\",\"msg\":\"" )+ex.what()+"\"}"; emit("/api/control/release", r.status); return r; }
    }
    if (path.rfind("/api/subscriptions", 0) == 0) {
      auto pos = std::string::npos;
      if (method == "POST" && path.rfind("/api/subscriptions",0)==0) {
        // naive JSON parse: extract fields by key
        auto extract = [&](const char* key) {
          auto k = std::string("\"") + key + "\"";
          auto p = body.find(k);
          if (p == std::string::npos) return std::string("");
          p = body.find(':', p);
          if (p == std::string::npos) return std::string("");
          auto q1 = body.find('"', p+1);
          if (q1 == std::string::npos) return std::string("");
          auto q2 = body.find('"', q1+1);
          if (q2 == std::string::npos) return std::string("");
          return body.substr(q1+1, q2-q1-1);
        };
        std::string stream_id = extract("stream_id");
        std::string profile   = extract("profile");
        std::string source_uri= extract("source_uri");
        std::string source_id = extract("source_id");
        std::string model_id  = extract("model_id");
        if (!source_id.empty() && source_uri.empty()) {
          // translate source_id -> restream URL from config
          source_uri = cfg.restream_rtsp_base + source_id;
        }
        if (stream_id.empty() || profile.empty() || source_uri.empty()) {
          // fallback: parse query string if present
          auto q = path.find('?');
          if (q != std::string::npos) {
            auto qs = path.substr(q+1);
            auto url_decode = [&](const std::string& s){
              std::string out; out.reserve(s.size());
              for (size_t i=0; i<s.size(); ++i) {
                char c = s[i];
                if (c == '+') { out.push_back(' '); continue; }
                if (c == '%' && i+2 < s.size()) {
                  auto hex = s.substr(i+1,2);
                  char* end=nullptr; long v = strtol(hex.c_str(), &end, 16);
                  if (end && *end=='\0') { out.push_back(static_cast<char>(v)); i+=2; continue; }
                }
                out.push_back(c);
              }
              return out;
            };
            auto getq = [&](const char* key){
              auto k = std::string(key) + "=";
              auto p = qs.find(k);
              if (p==std::string::npos) return std::string("");
              p += k.size();
              auto e = qs.find('&', p);
              auto v = qs.substr(p, e==std::string::npos? std::string::npos : e-p);
              return url_decode(v);
            };
            if (stream_id.empty()) stream_id = getq("stream_id");
            if (profile.empty()) profile = getq("profile");
            if (source_uri.empty()) source_uri = getq("source_uri");
            if (model_id.empty()) model_id = getq("model_id");
            if (source_uri.empty()) {
              auto sid = getq("source_id");
              if (!sid.empty()) source_uri = cfg.restream_rtsp_base + sid;
            }
          }
        }
        if (stream_id.empty() || profile.empty() || source_uri.empty()) {
          r.status = 400; r.body = "{\"code\":\"INVALID_ARGUMENT\"}"; return r;
        }
        // In minimal smoke mode (CP_FAKE_WATCH=1), accept subscription without contacting VA
        std::string va_id;
        bool fake_mode = false; {
          const char* fw = std::getenv("CP_FAKE_WATCH");
          if (fw) { std::string v(fw); for (auto& c : v) c = (char)std::tolower((unsigned char)c); fake_mode = (v=="1"||v=="true"); }
        }
        std::string err;
        if (!fake_mode) {
          // 允许使用 Triton 仓库模型名作为 "model_id"：
          // 若传入的 model_id 命中 /api/repo/list（VA RepoList），则先全局切换引擎至 provider=triton 且 triton_model=model_id，
          // 随后将订阅的 model_id 置空，避免 VA 侧按“检测模型 ID”查表失败。
          if (!model_id.empty()) {
            try {
              std::vector<std::string> repo_models; std::string e2;
              if (va_repo_list(cfg.va_addr, &repo_models, &e2)) {
                bool is_triton_repo_id = false;
                for (const auto& m : repo_models) { if (m == model_id) { is_triton_repo_id = true; break; } }
                if (is_triton_repo_id) {
                  auto stub = controlplane::make_va_stub(cfg.va_addr);
                  va::v1::SetEngineRequest sreq; va::v1::SetEngineReply srep; grpc::ClientContext sctx;
                  // 仅设置 triton_model 选项，不改变 provider（引擎已在配置中指定为 triton）
                  (*sreq.mutable_options())["triton_model"] = model_id;
                  auto st = stub->SetEngine(&sctx, sreq, &srep);
                  if (!st.ok() || !srep.ok()) {
                    auto mm=cp_map_err(st.error_message()); r.status=mm.code;
                    r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+(st.ok()? srep.msg(): st.error_message())+"\"}"; return r;
                  }
                  // 清空 model_id，避免 VA 按检测模型索引校验失败
                  model_id.clear();
                }
              }
            } catch (...) { /* best-effort */ }
          }
          if (!va_subscribe(cfg.va_addr, stream_id, profile, source_uri, model_id, &va_id, &err)) {
            auto mm = cp_map_err(err);
            r.status = mm.code; r.body = std::string("{\"code\":\"") + mm.text + "\",\"msg\":\"" + err + "\"}"; return r;
          }
        } else {
          va_id = std::string("fake-") + stream_id;
        }
        auto& st = Store::instance();
        auto cp_id = st.create(stream_id, profile, source_uri, model_id, va_id);
        r.status = 202;
        // Do not clobber CORS header set earlier; append Location and expose headers
        r.extraHeaders += std::string("Location: /api/subscriptions/") + cp_id + "\r\n";
        r.extraHeaders += "Access-Control-Expose-Headers: Location, ETag, Accept-Patch\r\n";
        r.body = std::string("{\"code\":\"ACCEPTED\",\"data\":{\"id\":\"") + cp_id + "\"}}";
        emit("/api/subscriptions", r.status);
        return r;
      }
      // SSE (events) placeholder: waiting for VA Watch streaming RPC
      if (method == "GET" && path.size() > strlen("/api/subscriptions/") && path.find("/events") == path.size()-7) {
        // e.g., /api/subscriptions/{id}/events
        r.status = 501;
        r.body = "{\"code\":\"VA_WATCH_UNAVAILABLE\",\"msg\":\"SSE requires VA Watch streaming RPC\"}";
        emit("/api/subscriptions/{id}/events", r.status);
        return r;
      }
      if (method == "GET") {
        // Support query string (e.g. /api/subscriptions/{id}?include=timeline)
        std::string raw_path = path;
        auto qmark = raw_path.find('?');
        const std::string prefix = "/api/subscriptions/";
        auto pfx = raw_path.find(prefix);
        if (pfx != 0) { r.status = 404; r.body = "{}"; return r; }
        size_t start = pfx + prefix.size();
        size_t end = (qmark==std::string::npos) ? raw_path.size() : qmark;
        if (start >= end) { r.status = 404; r.body = "{}"; return r; }
        auto cp_id = raw_path.substr(start, end - start);
        auto rec = Store::instance().get(cp_id);
        if (!rec) { r.status = 404; r.body = "{\"code\":\"NOT_FOUND\"}"; return r; }
        auto etag = Store::make_etag(*rec);
        // If-None-Match handling (very small parse)
        bool not_modified = false;
        auto hpos = headers.find("If-None-Match:");
        if (hpos != std::string::npos) {
          auto lend = headers.find("\r\n", hpos);
          auto val = headers.substr(hpos + strlen("If-None-Match:"), lend==std::string::npos? std::string::npos : lend-(hpos+strlen("If-None-Match:")));
          size_t b=0; while (b<val.size() && (val[b]==' '||val[b]=='\t')) ++b; val = val.substr(b);
          if (val==etag) not_modified = true;
        }
        r.extraHeaders += std::string("ETag: ") + etag + "\r\nAccess-Control-Expose-Headers: ETag,Location\r\n";
        if (not_modified) { r.status = 304; r.body = ""; emit("/api/subscriptions/{id}", r.status); return r; }

        // Derive live phase from VA pipelines when possible
        std::string phase = rec->last.phase;
        std::string reason = rec->last.reason;
        if (!rec->va_subscription_id.empty()) {
          try {
            auto stub = controlplane::make_va_stub(cfg.va_addr);
            grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
            va::v1::ListPipelinesRequest preq; va::v1::ListPipelinesReply prep;
            auto s = stub->ListPipelines(&ctx, preq, &prep);
            if (s.ok()) {
              for (const auto& it : prep.items()) {
                if (it.key() == rec->va_subscription_id) {
                  if (it.running()) { phase = "ready"; reason.clear(); }
                  break;
                }
              }
            }
          } catch (...) {}
        }

        // Optional: include=timeline
        bool want_timeline = false;
        if (qmark != std::string::npos) {
          auto qs = raw_path.substr(qmark+1);
          auto has_inc = qs.find("include=");
          if (has_inc != std::string::npos) {
            // very small check for 'timeline' token
            want_timeline = (qs.find("timeline", has_inc) != std::string::npos);
          }
        }
        std::ostringstream os;
        os << "{\"code\":\"OK\",\"data\":{\"id\":\"" << rec->cp_id
           << "\",\"phase\":\"" << phase << "\"";
        if (!reason.empty()) os << ",\"reason\":\"" << reason << "\"";
        os << ",\"created_at\":" << rec->last.ts_ms;
        os << ",\"pipeline_key\":\"" << rec->va_subscription_id << "\"";
        if (want_timeline) {
          os << ",\"timeline\":[{\"phase\":\"" << rec->last.phase << "\",\"ts_ms\":" << rec->last.ts_ms;
          if (!rec->last.reason.empty()) os << ",\"reason\":\"" << rec->last.reason << "\"";
          os << "}]";
        }
        os << "}}";
        r.status = 200; r.body = os.str(); emit("/api/subscriptions/{id}", r.status); return r;
      }
      if (method == "DELETE" && (pos = path.find_last_of('/')) != std::string::npos && pos+1 < path.size()) {
        auto cp_id = path.substr(pos+1);
        auto rec = Store::instance().get(cp_id);
        if (!rec) { r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; return r; } // idempotent
        std::string err;
        if (!va_unsubscribe(cfg.va_addr, rec->stream_id, rec->profile, &err)) {
          // best-effort cancel
        }
        Store::instance().set_phase(cp_id, "cancelled");
        r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; emit("/api/subscriptions/{id}", r.status); return r;
      }
      r.status = 404; r.body = "{}"; return r;
    }
    // WHEP reverse proxy: CP -> VA REST (default 127.0.0.1:8082)
    if (path.rfind("/whep", 0) == 0) {
      // CORS preflight
      if (method == "OPTIONS") {
        r.status = 200; r.body = "";
        r.extraHeaders += "Access-Control-Allow-Origin: *\r\n";
        r.extraHeaders += "Access-Control-Allow-Methods: POST, PATCH, DELETE, OPTIONS\r\n";
        r.extraHeaders += "Access-Control-Allow-Headers: Content-Type, Accept, Authorization, If-Match\r\n";
        r.extraHeaders += "Access-Control-Max-Age: 86400\r\n";
        emit("/whep", r.status); return r;
      }
      // Resolve VA REST host:port
      std::string va_host = "127.0.0.1"; int va_port = 8082;
      try {
        const char* env = std::getenv("VA_REST_BASE");
        if (env) {
          std::string base(env);
          // accept http://host:port or host:port
          auto pos = base.find("://"); if (pos != std::string::npos) base = base.substr(pos+3);
          auto colon = base.find(':');
          if (colon != std::string::npos) { va_host = base.substr(0, colon); va_port = std::stoi(base.substr(colon+1)); }
          else { va_host = base; }
        }
      } catch (...) {}
      std::string out_loc;
      HttpResponse proxied;
      if (!controlplane::proxy_http_simple(va_host, va_port, method, path, headers, body, &proxied, &out_loc)) {
        r.status = 502; r.body = "{\"code\":\"BACKEND_ERROR\"}"; emit("/whep", r.status); return r;
      }
      r = std::move(proxied);
      // CORS allow + expose Location/ETag/Accept-Patch to JS
      r.extraHeaders += "Access-Control-Allow-Origin: *\r\n";
      r.extraHeaders += "Access-Control-Expose-Headers: Location, ETag, Accept-Patch\r\n";
      // Rewrite Location to CP-relative when present (keep path only)
      if (!out_loc.empty()) {
        try {
          std::string rel = out_loc;
          auto scheme = rel.find("://");
          if (scheme != std::string::npos) {
            auto slash2 = rel.find('/', scheme+3);
            if (slash2 != std::string::npos) rel = rel.substr(slash2);
          }
          if (rel.rfind("/whep", 0) != 0) { // ensure prefix
            auto p = rel.find("/whep"); if (p != std::string::npos) rel = rel.substr(p);
          }
          if (!rel.empty()) r.extraHeaders += std::string("Location: ") + rel + "\r\n";
        } catch (...) {}
      }
      emit("/whep", r.status); return r;
    }
    // Control: set pipeline analysis mode (proxy to VA REST)
    if (path == "/api/control/pipeline_mode" && method == "POST") {
      // Resolve VA REST host:port (reuse VA_REST_BASE when present)
      std::string va_host = "127.0.0.1"; int va_port = 8082;
      try {
        const char* env = std::getenv("VA_REST_BASE");
        if (env) {
          std::string base(env);
          auto pos = base.find("://"); if (pos != std::string::npos) base = base.substr(pos+3);
          auto colon = base.find(':');
          if (colon != std::string::npos) { va_host = base.substr(0, colon); va_port = std::stoi(base.substr(colon+1)); }
          else { va_host = base; }
        }
      } catch (...) {}
      // minimal logging for diagnosis
      std::fprintf(stderr, "[CP] proxy pipeline_mode -> %s:%d\n", va_host.c_str(), va_port);
      controlplane::HttpResponse proxied;
      if (!controlplane::proxy_http_simple(va_host, va_port, method, path, headers, body, &proxied, nullptr)) {
        r.status = 502; r.body = "{\"code\":\"BACKEND_ERROR\"}"; emit("/api/control/pipeline_mode", r.status); return r;
      }
      r = std::move(proxied);
      std::fprintf(stderr, "[CP] proxy pipeline_mode status=%d\n", r.status);
      r.extraHeaders += "Access-Control-Allow-Origin: *\r\n";
      emit("/api/control/pipeline_mode", r.status); return r;
    }
  if (path == "/metrics") {
      r.contentType = "text/plain; version=0.0.4; charset=utf-8";
      r.body = controlplane::metrics::render_prometheus(); emit("/metrics", 200); return r;
    }
    // VSM sources endpoints
    if (path == "/api/sources" && method == "GET") {
      // Try WatchState single snapshot; fallback to GetHealth
      // cache: 1.5s TTL
      {
        std::string cached;
        if (controlplane::cache::SimpleCache::instance().get("sources", 1500, &cached)) {
          r.status = 200; r.body = cached; emit("/api/sources", r.status); return r;
        }
      }
      std::ostringstream os;
      os << "{\"code\":\"OK\",\"data\":{\"items\":[";
      bool first = true;
      bool ok = false;
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        vsm::v1::WatchStateRequest req; req.set_interval_ms(0);
        std::unique_ptr< grpc::ClientReader<vsm::v1::WatchStateReply> > reader(stub->WatchState(&ctx, req));
        vsm::v1::WatchStateReply rep;
        if (reader && reader->Read(&rep)) {
          for (const auto& it : rep.items()) {
            if (!first) os << ","; first=false;
            os << "{\"attach_id\":\""<<it.attach_id()<<"\",\"source_uri\":\""<<it.source_uri()
               <<"\",\"phase\":\""<<it.phase()<<"\",\"fps\":"<<it.fps();
            if (!it.profile().empty()) os << ",\"profile\":\""<<it.profile()<<"\"";
            if (!it.model_id().empty()) os << ",\"model_id\":\""<<it.model_id()<<"\"";
            os << "}";
          }
          ok = true;
        }
        if (reader) reader->Finish();
      } catch (...) {}
      if (!ok) {
        try {
          auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
          grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
          vsm::v1::GetHealthRequest req; vsm::v1::GetHealthReply rep; auto s = stub->GetHealth(&ctx, req, &rep);
          if (s.ok()) {
            for (const auto& st : rep.streams()) {
              if (!first) os << ","; first=false;
              os << "{\"attach_id\":\""<<st.attach_id()<<"\",\"fps\":"<<st.fps()<<",\"phase\":\""<<st.phase()<<"\"}";
            }
          }
        } catch (...) {}
      }
      if (first) {
        // Synthesize one default source from restream base when none reported
        try {
          std::string sid = "camera_01";
          std::string uri = cfg.restream_rtsp_base + sid;
          os << "{\"attach_id\":\"" << sid << "\",\"source_uri\":\"" << uri << "\",\"phase\":\"Ready\"}";
          first = false;
        } catch (...) {}
      }
      os << "]}}";
      r.status = 200; r.body = os.str(); controlplane::cache::SimpleCache::instance().put("sources", r.body); emit("/api/sources", r.status); return r;
    }
    if (path.rfind("/api/sources:attach",0)==0 && method == "POST") {
      // parse attach_id, source_uri, pipeline_id (optional options)
      auto extract = [&](const char* key) {
        auto k = std::string("\"") + key + "\"";
        auto p = body.find(k);
        if (p == std::string::npos) return std::string("");
        p = body.find(':', p);
        if (p == std::string::npos) return std::string("");
        auto q1 = body.find('"', p+1);
        if (q1 == std::string::npos) return std::string("");
        auto q2 = body.find('"', q1+1);
        if (q2 == std::string::npos) return std::string("");
        return body.substr(q1+1, q2-q1-1);
      };
      std::string attach_id = extract("attach_id");
      std::string source_uri= extract("source_uri");
      std::string pipeline_id = extract("pipeline_id");
      if (attach_id.empty() || source_uri.empty()) {
        auto q = path.find('?');
        if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){
            auto k = std::string(key) + "=";
            auto p = qs.find(k);
            if (p==std::string::npos) return std::string("");
            p += k.size();
            auto e = qs.find('&', p);
            auto v = qs.substr(p, e==std::string::npos? std::string::npos : e-p);
            return v;
          };
          if (attach_id.empty()) attach_id = getq("attach_id");
          if (source_uri.empty()) source_uri = getq("source_uri");
          if (pipeline_id.empty()) pipeline_id = getq("pipeline_id");
        }
      }
      if (attach_id.empty() || source_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/sources:attach", r.status); return r; }
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000));
        vsm::v1::AttachRequest req; req.set_attach_id(attach_id); req.set_source_uri(source_uri); req.set_pipeline_id(pipeline_id);
        vsm::v1::AttachReply rep; auto s = stub->Attach(&ctx, req, &rep);
        if (!s.ok() || !rep.accepted()) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/sources:attach", r.status); return r; }
        r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/sources:attach", r.status); return r;
      } catch (...) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/sources:attach", r.status); return r; }
    }
    if (path.rfind("/api/sources:detach",0)==0 && method == "POST") {
      auto extract = [&](const char* key) {
        auto k = std::string("\"") + key + "\"";
        auto p = body.find(k);
        if (p == std::string::npos) return std::string("");
        p = body.find(':', p);
        if (p == std::string::npos) return std::string("");
        auto q1 = body.find('"', p+1);
        if (q1 == std::string::npos) return std::string("");
        auto q2 = body.find('"', q1+1);
        if (q2 == std::string::npos) return std::string("");
        return body.substr(q1+1, q2-q1-1);
      };
      std::string attach_id = extract("attach_id");
      if (attach_id.empty()) {
        auto q = path.find('?');
        if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){
            auto k = std::string(key) + "=";
            auto p = qs.find(k);
            if (p==std::string::npos) return std::string("");
            p += k.size();
            auto e = qs.find('&', p);
            auto v = qs.substr(p, e==std::string::npos? std::string::npos : e-p);
            return v;
          };
          attach_id = getq("attach_id");
        }
      }
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/sources:detach", r.status); return r; }
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000));
        vsm::v1::DetachRequest req; req.set_attach_id(attach_id);
        vsm::v1::DetachReply rep; auto s = stub->Detach(&ctx, req, &rep);
        if (!s.ok() || !rep.removed()) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/sources:detach", r.status); return r; }
        r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/sources:detach", r.status); return r;
      } catch (...) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/sources:detach", r.status); return r; }
    }
    if (path.rfind("/api/sources:enable",0)==0 && method == "POST") {
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      std::string attach_id;
      if (!body.empty()) { try { json j=json::parse(body); if (j.contains("attach_id")&&j["attach_id"].is_string()) attach_id=j["attach_id"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/sources:enable", r.status); return r; } }
      if (attach_id.empty()) attach_id = getq("attach_id");
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/sources:enable", r.status); return r; }
      std::string err;
      if (!vsm_set_enabled(cfg.vsm_addr, attach_id, true, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\"}"; emit("/api/sources:enable", r.status); return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/sources:enable", r.status); return r;
    }
    if (path.rfind("/api/sources:disable",0)==0 && method == "POST") {
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      std::string attach_id;
      if (!body.empty()) { try { json j=json::parse(body); if (j.contains("attach_id")&&j["attach_id"].is_string()) attach_id=j["attach_id"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/sources:disable", r.status); return r; } }
      if (attach_id.empty()) attach_id = getq("attach_id");
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/sources:disable", r.status); return r; }
      std::string err;
      if (!vsm_set_enabled(cfg.vsm_addr, attach_id, false, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\"}"; emit("/api/sources:disable", r.status); return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/sources:disable", r.status); return r;
    }
    // VA control: apply pipeline (M0 minimal)
    if (path.rfind("/api/control/apply_pipeline", 0) == 0 && method == "POST") {
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      std::string pipeline_name, yaml_path, graph_id, serialized, format, revision;
      if (!body.empty()) {
        try {
          nlohmann::json j = nlohmann::json::parse(body);
          if (j.contains("pipeline_name") && j["pipeline_name"].is_string()) pipeline_name = j["pipeline_name"].get<std::string>();
          if (j.contains("revision") && j["revision"].is_string()) revision = j["revision"].get<std::string>();
          if (j.contains("spec") && j["spec"].is_object()) {
            auto& s = j["spec"];
            if (s.contains("yaml_path") && s["yaml_path"].is_string()) yaml_path = s["yaml_path"].get<std::string>();
            if (s.contains("graph_id") && s["graph_id"].is_string()) graph_id = s["graph_id"].get<std::string>();
            if (s.contains("serialized") && s["serialized"].is_string()) serialized = s["serialized"].get<std::string>();
            if (s.contains("format") && s["format"].is_string()) format = s["format"].get<std::string>();
          } else {
            if (j.contains("yaml_path") && j["yaml_path"].is_string()) yaml_path = j["yaml_path"].get<std::string>();
            if (j.contains("graph_id") && j["graph_id"].is_string()) graph_id = j["graph_id"].get<std::string>();
            if (j.contains("serialized") && j["serialized"].is_string()) serialized = j["serialized"].get<std::string>();
            if (j.contains("format") && j["format"].is_string()) format = j["format"].get<std::string>();
          }
        } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/apply_pipeline", r.status); return r; }
      }
      if (pipeline_name.empty()) pipeline_name = getq("pipeline_name");
      if (yaml_path.empty()) yaml_path = getq("yaml_path");
      if (graph_id.empty()) graph_id = getq("graph_id");
      if (serialized.empty()) serialized = getq("serialized");
      if (format.empty()) format = getq("format");
      if (revision.empty()) revision = getq("revision");
      if (pipeline_name.empty() || (yaml_path.empty() && graph_id.empty() && serialized.empty())) {
        r.status = 400; r.body = "{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/apply_pipeline", r.status); return r;
      }
      std::string err2;
      if (!va_apply_pipeline(cfg.va_addr, pipeline_name, yaml_path, graph_id, serialized, format, revision, &err2)) {
        auto mm = cp_map_err(err2);
        r.status = mm.code; r.body = std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err2+"\"}"; emit("/api/control/apply_pipeline", r.status); return r;
      }
      r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; emit("/api/control/apply_pipeline", r.status); return r;
    }
    // VA control: remove pipeline by name (DELETE)
    if (path.rfind("/api/control/pipeline", 0) == 0 && method == "DELETE") {
      std::string pipeline_name;
      // Prefer query param pipeline_name
      auto q = path.find('?');
      if (q != std::string::npos) {
        auto qs = path.substr(q+1);
        auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
        pipeline_name = getq("pipeline_name");
      }
      if (pipeline_name.empty() && !body.empty()) {
        try { nlohmann::json j = nlohmann::json::parse(body); if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/pipeline", r.status); return r; }
      }
      if (pipeline_name.empty()) { r.status = 400; r.body = "{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/pipeline", r.status); try { controlplane::logging::audit("control.pipeline_delete.request", corr_id, {{"pipeline_name", pipeline_name}}); controlplane::logging::audit("control.pipeline_delete.response", corr_id, {{"status", r.status}}); } catch (...) {} return r; }
      try { controlplane::logging::audit("control.pipeline_delete.request", corr_id, {{"pipeline_name", pipeline_name}}); } catch (...) {}
      std::string err3;
      if (!va_remove_pipeline(cfg.va_addr, pipeline_name, &err3)) {
        auto mm = cp_map_err(err3);
        r.status = mm.code; r.body = std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err3+"\"}"; emit("/api/control/pipeline", r.status); try { controlplane::logging::audit("control.pipeline_delete.response", corr_id, {{"status", r.status}, {"msg", err3}}); } catch (...) {} return r;
      }
      r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; emit("/api/control/pipeline", r.status); try { controlplane::logging::audit("control.pipeline_delete.response", corr_id, {{"status", r.status}}); } catch (...) {} return r;
    }
    // VA control: batch apply pipelines
    if (path.rfind("/api/control/apply_pipelines", 0) == 0 && method == "POST") {
      std::vector<controlplane::ApplyItem> items;
      try {
        nlohmann::json j = nlohmann::json::parse(body);
        const nlohmann::json* arr = nullptr;
        if (j.is_array()) arr = &j; else if (j.contains("items") && j["items"].is_array()) arr = &j["items"];
        if (!arr) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"items array required\"}"; emit("/api/control/apply_pipelines", r.status); return r; }
        for (auto& it : *arr) {
          if (!it.is_object()) continue;
          controlplane::ApplyItem ai;
          if (it.contains("pipeline_name") && it["pipeline_name"].is_string()) ai.pipeline_name = it["pipeline_name"].get<std::string>();
          if (it.contains("revision") && it["revision"].is_string()) ai.revision = it["revision"].get<std::string>();
          const nlohmann::json* spec = nullptr;
          if (it.contains("spec") && it["spec"].is_object()) spec = &it["spec"]; else spec = &it;
          if (spec->contains("yaml_path") && (*spec)["yaml_path"].is_string()) ai.yaml_path = (*spec)["yaml_path"].get<std::string>();
          if (spec->contains("graph_id") && (*spec)["graph_id"].is_string()) ai.graph_id = (*spec)["graph_id"].get<std::string>();
          if (spec->contains("serialized") && (*spec)["serialized"].is_string()) ai.serialized = (*spec)["serialized"].get<std::string>();
          if (spec->contains("format") && (*spec)["format"].is_string()) ai.format = (*spec)["format"].get<std::string>();
          if (!ai.pipeline_name.empty()) items.push_back(std::move(ai));
        }
      } catch (...) { r.status=400; r.body = "{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/apply_pipelines", r.status); return r; }
      if (items.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/apply_pipelines", r.status); return r; }
      int accepted = 0; std::vector<std::string> errors; std::string errb;
      if (!va_apply_pipelines(cfg.va_addr, items, &accepted, &errors, &errb)) {
        r.status=502; r.body = "{\"code\":\"BACKEND_ERROR\",\"msg\":\""+errb+"\"}"; emit("/api/control/apply_pipelines", r.status); return r;
      }
      std::ostringstream os; os << "{\"code\":\"ACCEPTED\",\"accepted\":"<<accepted;
      if (!errors.empty()) { os << ",\"errors\":["; for (size_t i=0;i<errors.size();++i){ if(i) os<<","; os<<"\""<<errors[i]<<"\"";} os<<"]"; }
      os << "}";
      r.status=202; r.body=os.str(); emit("/api/control/apply_pipelines", r.status); return r;
    }
    // VA control: hotswap model
    if (path.rfind("/api/control/hotswap", 0) == 0 && method == "POST") {
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      std::string pipeline_name, node, model_uri;
      if (!body.empty()) { try { nlohmann::json j=nlohmann::json::parse(body); if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>(); if (j.contains("node")&&j["node"].is_string()) node=j["node"].get<std::string>(); if (j.contains("model_uri")&&j["model_uri"].is_string()) model_uri=j["model_uri"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/hotswap", r.status); try { controlplane::logging::audit("control.hotswap.request", corr_id, {{"pipeline_name", pipeline_name},{"node",node},{"model_uri",model_uri}}); controlplane::logging::audit("control.hotswap.response", corr_id, {{"status", r.status}});} catch (...) {} return r; } }
      if (pipeline_name.empty()) pipeline_name = getq("pipeline_name");
      if (node.empty()) node = getq("node");
      if (model_uri.empty()) model_uri = getq("model_uri");
      try { controlplane::logging::audit("control.hotswap.request", corr_id, {{"pipeline_name", pipeline_name},{"node",node},{"model_uri",model_uri}});} catch (...) {}
      if (pipeline_name.empty() || node.empty() || model_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/hotswap", r.status); try { controlplane::logging::audit("control.hotswap.response", corr_id, {{"status", r.status}});} catch (...) {} return r; }
      std::string errh; if (!va_hotswap_model(cfg.va_addr, pipeline_name, node, model_uri, &errh)) { auto mm=cp_map_err(errh); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errh+"\"}"; emit("/api/control/hotswap", r.status); try { controlplane::logging::audit("control.hotswap.response", corr_id, {{"status", r.status}, {"msg", errh}});} catch (...) {} return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/control/hotswap", r.status); try { controlplane::logging::audit("control.hotswap.response", corr_id, {{"status", r.status}});} catch (...) {} return r;
    }
    // VA control: get status
    if (path.rfind("/api/control/status", 0) == 0 && method == "GET") {
      std::string pipeline_name;
      auto q = path.find('?'); if (q!=std::string::npos) {
        auto qs = path.substr(q+1);
        auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
        pipeline_name = getq("pipeline_name");
      }
      if (pipeline_name.empty() && !body.empty()) {
        try { nlohmann::json j = nlohmann::json::parse(body); if (j.contains("pipeline_name") && j["pipeline_name"].is_string()) pipeline_name = j["pipeline_name"].get<std::string>(); } catch (...) { /* ignore body */ }
      }
      if (pipeline_name.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/status", r.status); return r; }
      std::string phase, metrics_json, errs;
      if (!va_get_status(cfg.va_addr, pipeline_name, &phase, &metrics_json, &errs)) { auto mm=cp_map_err(errs); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errs+"\"}"; emit("/api/control/status", r.status); return r; }
      std::ostringstream os; os << "{\"code\":\"OK\",\"data\":{\"pipeline_name\":\""<<pipeline_name<<"\",\"phase\":\""<<phase<<"\""; if(!metrics_json.empty()){ os<<",\"metrics\":"<<metrics_json; } os << "}}";
      r.status=200; r.body=os.str(); emit("/api/control/status", r.status); return r;
    }
    // VA control: drain pipeline
    if (path.rfind("/api/control/drain", 0) == 0 && method == "POST") {
      std::string pipeline_name; int timeout_sec = 0;
      if (!body.empty()) { try { nlohmann::json j = nlohmann::json::parse(body); if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>(); if (j.contains("timeout_sec")&&j["timeout_sec"].is_number_integer()) timeout_sec=j["timeout_sec"].get<int>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/control/drain", r.status); try { controlplane::logging::audit("control.drain.request", corr_id, {{"pipeline_name", pipeline_name},{"timeout_sec", timeout_sec}}); controlplane::logging::audit("control.drain.response", corr_id, {{"status", r.status}});} catch (...) {} return r; } }
      if (pipeline_name.empty()) {
        auto q = path.find('?'); if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
          pipeline_name = getq("pipeline_name");
          auto ts = getq("timeout_sec"); if (!ts.empty()) { try { timeout_sec = std::stoi(ts); } catch(...) {} }
        }
      }
      try { controlplane::logging::audit("control.drain.request", corr_id, {{"pipeline_name", pipeline_name},{"timeout_sec", timeout_sec}});} catch (...) {}
      if (pipeline_name.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/control/drain", r.status); try { controlplane::logging::audit("control.drain.response", corr_id, {{"status", r.status}});} catch (...) {} return r; }
      bool drained=false; std::string erd; if (!va_drain(cfg.va_addr, pipeline_name, timeout_sec, &drained, &erd)) { auto mm=cp_map_err(erd); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+erd+"\"}"; emit("/api/control/drain", r.status); return r; }
      r.status=202; r.body = std::string("{\"code\":\"ACCEPTED\",\"drained\":") + (drained?"true":"false") + "}"; emit("/api/control/drain", r.status); try { controlplane::logging::audit("control.drain.response", corr_id, {{"status", r.status},{"drained", drained}});} catch (...) {} return r;
    }
    // Orchestration endpoints
    if (path.rfind("/api/orch/attach_apply", 0) == 0 && method == "POST") {
      using nlohmann::json;
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      std::string attach_id, source_uri, source_id, pipeline_name;
      std::string yaml_path, graph_id, serialized, format, revision;
      if (!body.empty()) {
        try {
          json j = json::parse(body);
          if (j.contains("attach_id")&&j["attach_id"].is_string()) attach_id=j["attach_id"].get<std::string>();
          if (j.contains("source_uri")&&j["source_uri"].is_string()) source_uri=j["source_uri"].get<std::string>();
          if (j.contains("source_id")&&j["source_id"].is_string()) source_id=j["source_id"].get<std::string>();
          if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>();
          if (j.contains("spec")&&j["spec"].is_object()) {
            auto& s=j["spec"]; if (s.contains("yaml_path")&&s["yaml_path"].is_string()) yaml_path=s["yaml_path"].get<std::string>();
            if (s.contains("graph_id")&&s["graph_id"].is_string()) graph_id=s["graph_id"].get<std::string>();
            if (s.contains("serialized")&&s["serialized"].is_string()) serialized=s["serialized"].get<std::string>();
            if (s.contains("format")&&s["format"].is_string()) format=s["format"].get<std::string>();
            if (s.contains("revision")&&s["revision"].is_string()) revision=s["revision"].get<std::string>();
          }
        } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/orch/attach_apply", r.status); return r; }
      }
      if (attach_id.empty()) attach_id = getq("attach_id");
      if (source_uri.empty()) source_uri = getq("source_uri");
      if (source_id.empty()) source_id = getq("source_id");
      if (pipeline_name.empty()) pipeline_name = getq("pipeline_name");
      if (source_uri.empty() && !source_id.empty()) source_uri = cfg.restream_rtsp_base + source_id;
      try { controlplane::logging::audit("orch.attach_apply.request", corr_id, {{"attach_id", attach_id}, {"source_uri", source_uri}, {"source_id", source_id}, {"pipeline_name", pipeline_name}}); } catch (...) {}
      if (attach_id.empty() || source_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/orch/attach_apply", r.status); try { controlplane::logging::audit("orch.attach_apply.response", corr_id, {{"status", r.status}, {"reason", "missing attach_id/source_uri"}}); } catch (...) {} return r; }
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000));
        vsm::v1::AttachRequest req; vsm::v1::AttachReply rep;
        req.set_attach_id(attach_id); req.set_source_uri(source_uri);
        if (!pipeline_name.empty()) req.set_pipeline_id(pipeline_name);
        auto s = stub->Attach(&ctx, req, &rep);
        if (!s.ok()) {
          controlplane::set_last_grpc_status_code(s.error_code());
          // 幂等：已存在视为成功
          if (s.error_code() != grpc::StatusCode::ALREADY_EXISTS) {
            auto mm = cp_map_err(s.error_message()); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+s.error_message()+"\"}"; emit("/api/orch/attach_apply", r.status); try { controlplane::logging::audit("orch.attach_apply.vsm_attach", corr_id, {{"status", r.status}, {"grpc_code", controlplane::last_grpc_status_code()}, {"msg", s.error_message()}, {"attach_id", attach_id}}); } catch (...) {} return r;
          }
        }
        // s.ok() 或 ALREADY_EXISTS 时继续
        if (s.ok() && !rep.accepted()) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/orch/attach_apply", r.status); try { controlplane::logging::audit("orch.attach_apply.vsm_attach", corr_id, {{"status", r.status}, {"accepted", false}, {"attach_id", attach_id}}); } catch (...) {} return r; }
      } catch (const std::exception& ex) { r.status=502; r.body=std::string("{\"code\":\"BACKEND_ERROR\",\"msg\":\"")+ex.what()+"\"}"; emit("/api/orch/attach_apply", r.status); return r; } catch (...) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; emit("/api/orch/attach_apply", r.status); return r; }
      // optional: apply pipeline on VA when spec/pipeline_name provided
      if (!pipeline_name.empty() || !yaml_path.empty() || !graph_id.empty() || !serialized.empty()) {
        if (pipeline_name.empty()) pipeline_name = attach_id;
        std::string errva;
        if (!va_apply_pipeline(cfg.va_addr, pipeline_name, yaml_path, graph_id, serialized, format, revision, &errva)) {
          // best-effort detach
          try { controlplane::logging::audit("orch.attach_apply.va_apply_failed", corr_id, {{"pipeline_name", pipeline_name}, {"msg", errva}}); } catch (...) {}
          try { auto stub = controlplane::make_vsm_stub(cfg.vsm_addr); grpc::ClientContext c2; c2.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(3000)); vsm::v1::DetachRequest q; vsm::v1::DetachReply p; q.set_attach_id(attach_id); stub->Detach(&c2, q, &p); try { controlplane::logging::audit("orch.attach_apply.rollback.detach", corr_id, {{"attach_id", attach_id}, {"status", "attempted"}}); } catch (...) {} } catch (...) { try { controlplane::logging::audit("orch.attach_apply.rollback.detach", corr_id, {{"attach_id", attach_id}, {"status", "error"}}); } catch (...) {} }
          auto mm = cp_map_err(errva); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errva+"\"}"; emit("/api/orch/attach_apply", r.status); return r;
        }
      }
      r.status=202; r.body = std::string("{\"code\":\"ACCEPTED\",\"attach_id\":\"")+attach_id+"\",\"pipeline_name\":\""+pipeline_name+"\"}"; emit("/api/orch/attach_apply", r.status); try { controlplane::logging::audit("orch.attach_apply.response", corr_id, {{"status", r.status}, {"attach_id", attach_id}, {"pipeline_name", pipeline_name}}); } catch (...) {} return r;
    }
    if (path.rfind("/api/orch/detach_remove", 0) == 0 && method == "POST") {
      using nlohmann::json; std::string attach_id, pipeline_name;
      auto getq = [&](const std::string& key){ auto q=path.find('?'); if(q==std::string::npos) return std::string(); auto qs=path.substr(q+1); auto k=key+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos:e-p); };
      if (!body.empty()) { try { json j=json::parse(body); if (j.contains("attach_id")&&j["attach_id"].is_string()) attach_id=j["attach_id"].get<std::string>(); if (j.contains("pipeline_name")&&j["pipeline_name"].is_string()) pipeline_name=j["pipeline_name"].get<std::string>(); } catch (...) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\",\"msg\":\"INVALID_JSON\"}"; emit("/api/orch/detach_remove", r.status); return r; } }
      if (attach_id.empty()) attach_id = getq("attach_id"); if (pipeline_name.empty()) pipeline_name = getq("pipeline_name");
      if (attach_id.empty() && pipeline_name.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; emit("/api/orch/detach_remove", r.status); try { controlplane::logging::audit("orch.detach_remove.response", corr_id, {{"status", r.status}, {"reason", "missing attach_id/pipeline_name"}}); } catch (...) {} return r; }
      // best-effort detach/remove
      try { if (!attach_id.empty()) { auto stub=controlplane::make_vsm_stub(cfg.vsm_addr); grpc::ClientContext c; c.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000)); vsm::v1::DetachRequest q; vsm::v1::DetachReply p; q.set_attach_id(attach_id); stub->Detach(&c,q,&p); } } catch (...) {}
      try { if (!pipeline_name.empty()) { std::string er; va_remove_pipeline(cfg.va_addr, pipeline_name, &er); } } catch (...) {}
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; emit("/api/orch/detach_remove", r.status); try { controlplane::logging::audit("orch.detach_remove.response", corr_id, {{"status", r.status}, {"attach_id", attach_id}, {"pipeline_name", pipeline_name}}); } catch (...) {} return r;
    }
    if (path.rfind("/api/orch/health", 0) == 0 && method == "GET") {
      // Aggregate VSM GetHealth; optionally extend later with VA list/status
      std::ostringstream os; os << "{\"code\":\"OK\",\"data\":{\"streams\":[";
      bool first=true; bool ok=false;
      try { auto stub = controlplane::make_vsm_stub(cfg.vsm_addr); grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500)); vsm::v1::GetHealthRequest q; vsm::v1::GetHealthReply p; auto s = stub->GetHealth(&ctx, q, &p); if (s.ok()) { ok=true; for (const auto& st : p.streams()) { if(!first) os << ","; first=false; os << "{\"attach_id\":\""<<st.attach_id()<<"\",\"phase\":\""<<st.phase()<<"\",\"fps\":"<<st.fps()<<"}"; } } } catch (...) {}
      os << "]}}"; r.status = ok?200:200; r.body=os.str(); emit("/api/orch/health", r.status); return r;
    }
    if (path.rfind("/api/control", 0) == 0) {
      // Minimal apply endpoints for pipeline specs
      auto write_file = [](const std::string& file, const std::string& content) {
        try {
          std::filesystem::create_directories(std::filesystem::path(file).parent_path());
          std::ofstream ofs(file, std::ios::binary);
          ofs.write(content.data(), static_cast<std::streamsize>(content.size()));
          return ofs.good();
        } catch (...) { return false; }
      };
      auto nowms = [](){ using namespace std::chrono; return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count(); };

      if (method == "POST" && path == "/api/control/apply_pipeline") {
        // Persist a single pipeline spec for auditing; noop for runtime
        std::string name = "pipeline-from-ui";
        try {
          auto j = nlohmann::json::parse(body);
          if (j.contains("name") && j["name"].is_string()) name = j["name"].get<std::string>();
        } catch (...) {}
        std::ostringstream fn; fn << "controlplane/state/pipelines/" << name << "-" << nowms() << ".json";
        bool ok = write_file(fn.str(), body);
        nlohmann::json out; out["code"] = ok?"OK":"ERROR"; if (!ok) out["msg"] = "persist failed"; else out["data"] = { {"file", fn.str()} };
        r.status = ok?200:500; r.body = out.dump(); emit("/api/control/apply_pipeline", r.status); return r;
      }
      if (method == "POST" && path == "/api/control/apply_pipelines") {
        // Persist batch specs
        std::string all = body;
        std::ostringstream fn; fn << "controlplane/state/pipelines/batch-" << nowms() << ".json";
        bool ok = write_file(fn.str(), all);
        nlohmann::json out; out["code"] = ok?"OK":"ERROR"; if (!ok) out["msg"] = "persist failed"; else out["data"] = { {"file", fn.str()} };
        r.status = ok?200:500; r.body = out.dump(); emit("/api/control/apply_pipelines", r.status); return r;
      }
      std::ostringstream os; os << "{\"code\":\"NOT_FOUND\",\"path\":\"" << path << "\"}";
      r.status = 404; r.body = os.str(); return r;
    }
    r.status = 404; r.body = "{}"; return r;
  };
  // stream handler (SSE skeleton): emit SSE headers and an error event until VA Watch is available
  StreamRouteHandler streamHandler = [cfg](const std::string& method, const std::string& path, const std::string& headers, const std::string& body, StreamWriter writer) -> bool {
    (void)headers; (void)body;
    // Only handle SSE endpoint: /api/subscriptions/{id}/events
    if (method != "GET") return false;

    // Handle sources watch SSE: /api/sources/watch_sse or /api/sources/watch
    if (path.rfind("/api/sources/watch_sse", 0) == 0 || path.rfind("/api/sources/watch", 0) == 0) {
      try {
        auto stub = controlplane::make_vsm_stub(cfg.vsm_addr);
        grpc::ClientContext ctx;
        if (cfg.sse.idle_close_ms > 0) {
          ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(cfg.sse.idle_close_ms));
        }
        vsm::v1::WatchStateRequest req; req.set_interval_ms(cfg.sse.sources_interval_ms > 0 ? cfg.sse.sources_interval_ms : 1000);
        std::unique_ptr< grpc::ClientReader<vsm::v1::WatchStateReply> > reader(stub->WatchState(&ctx, req));
        if (!reader) throw std::runtime_error("VSM WatchState reader null");
        controlplane::sse::write_headers(writer);
        controlplane::metrics::sse_on_open();
        // Count request as accepted immediately (SSE opened)
        controlplane::metrics::inc_request("/api/sources/watch_sse", method, 200);
        // Emit an initial empty state to avoid client-side timeouts when there are no items yet
        controlplane::sse::write_event(writer, "state", "{\\\"items\\\":[]}");
        vsm::v1::WatchStateReply rep;
        long long last_keep = 0;
        auto nowms = [](){ using namespace std::chrono; return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count(); };
        while (reader->Read(&rep)) {
          std::ostringstream os;
          os << "{\\\"items\\\":[";
          bool first=true;
          for (const auto& it : rep.items()) {
            if (!first) os << ","; first=false;
            os << "{\\\"attach_id\\\":\\\""<<it.attach_id()<<"\\\",\\\"phase\\\":\\\""<<it.phase()<<"\\\",\\\"fps\\\":"<<it.fps();
            if (!it.profile().empty()) os << ",\\\"profile\\\":\\\""<<it.profile()<<"\\\"";
            if (!it.model_id().empty()) os << ",\\\"model_id\\\":\\\""<<it.model_id()<<"\\\"";
            if (!it.source_uri().empty()) os << ",\\\"source_uri\\\":\\\""<<it.source_uri()<<"\\\"";
            os << "}";
          }
          os << "]}";
          controlplane::sse::write_event(writer, "state", os.str());
          last_keep = nowms();
        }
        // close SSE and finish; count as 200
        if (nowms() - last_keep > cfg.sse.keepalive_ms) controlplane::sse::write_comment(writer, "keepalive");
        controlplane::sse::close(writer);
        controlplane::metrics::sse_on_close();
        try { reader->Finish(); } catch (...) {}
        return true;
      } catch (...) {
        controlplane::sse::write_headers(writer);
        controlplane::metrics::sse_on_open();
        controlplane::metrics::inc_request("/api/sources/watch_sse", method, 200);
        controlplane::sse::write_event(writer, "state", "{\\\"items\\\":[],\\\"error\\\":\\\"VSM_WATCH_UNAVAILABLE\\\"}");
        controlplane::sse::close(writer);
        controlplane::metrics::sse_on_close();
        return true;
      }
    }

    // Simple generic events stream for front-end compatibility: /api/events/stream
    if (path.rfind("/api/events/stream", 0) == 0) {
      controlplane::sse::write_headers(writer);
      controlplane::metrics::sse_on_open();
      // emit an initial event then periodic keepalive for a short period
      controlplane::sse::write_event(writer, "init", "{}");
      for (int i=0;i<30;i++) { // ~30*1s
        std::this_thread::sleep_for(std::chrono::seconds(1));
        controlplane::sse::write_comment(writer, "keepalive");
      }
      controlplane::sse::close(writer);
      controlplane::metrics::sse_on_close();
      controlplane::metrics::inc_request("/api/events/stream", method, 200);
      return true;
    }
    // Training progress/events SSE: /api/train/events?id=... (skeleton, in-process)
    if (path.rfind("/api/train/events", 0) == 0) {
      auto qpos = path.find('?'); std::string qs = (qpos==std::string::npos)? std::string("") : path.substr(qpos+1);
      auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
      std::string job = getq("id");
      std::shared_ptr<TrainJobRec> tj; { std::lock_guard<std::mutex> lk(g_train_mu); auto it=g_train_jobs.find(job); if(it!=g_train_jobs.end()) tj=it->second; }
      controlplane::sse::write_headers(writer);
      controlplane::metrics::sse_on_open();
      if (!tj) { controlplane::sse::write_event(writer, "error", "{\\\"code\\\":\\\"NOT_FOUND\\\"}"); controlplane::sse::close(writer); controlplane::metrics::sse_on_close(); return true; }
      size_t idx = 0; long long last_keep = 0; auto nowms=[](){ using namespace std::chrono; return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count(); };
      while (true) {
        {
          std::lock_guard<std::mutex> lk(tj->mu);
          while (idx < tj->events.size()) {
            auto& ev = tj->events[idx++];
            controlplane::sse::write_event(writer, ev.kind, ev.json);
            last_keep = nowms();
          }
          if (tj->done) { break; }
        }
        if (nowms() - last_keep > 8000) controlplane::sse::write_comment(writer, "keepalive");
        std::this_thread::sleep_for(std::chrono::milliseconds(200));
      }
      controlplane::sse::close(writer); controlplane::metrics::sse_on_close();
      return true;
    }
    // Handle conversion progress SSE: /api/repo/convert/events?job=... -> proxy VA RepoConvertStream
    if (path.rfind("/api/repo/convert/events", 0) == 0) {
      auto qpos = path.find('?'); std::string qs = (qpos==std::string::npos)? std::string("") : path.substr(qpos+1);
      auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
      std::string job_id = getq("job");
      controlplane::sse::write_headers(writer);
      controlplane::metrics::sse_on_open();
      try {
        auto stub = controlplane::make_va_stub(cfg.va_addr);
        grpc::ClientContext ctx; // long-running stream
        va::v1::RepoConvertStreamRequest req; req.set_job_id(job_id);
        std::unique_ptr< grpc::ClientReader<va::v1::RepoConvertEvent> > reader(stub->RepoConvertStream(&ctx, req));
        if (!reader) { controlplane::sse::write_event(writer, "error", "{\\\"code\\\":\\\"STREAM_OPEN_FAILED\\\"}"); controlplane::sse::close(writer); controlplane::metrics::sse_on_close(); return true; }
        va::v1::RepoConvertEvent ev; long long last_keep = 0; auto nowms=[](){ using namespace std::chrono; return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count(); };
        while (reader->Read(&ev)) {
          std::string kind = ev.kind();
          if (kind == "state") {
            std::string json = std::string("{\"phase\":\"") + ev.phase() + "\"";
            if (ev.progress() > 0.0f) { json += std::string(",\"progress\":") + std::to_string(ev.progress()); }
            json += "}";
            controlplane::sse::write_event(writer, "state", json);
            last_keep = nowms();
          } else if (kind == "done") {
            std::string json = std::string("{\"phase\":\"") + ev.phase() + "\"";
            if (ev.progress() > 0.0f) { json += std::string(",\"progress\":") + std::to_string(ev.progress()); }
            json += "}";
            controlplane::sse::write_event(writer, "done", json);
            break;
          }
          if (nowms() - last_keep > 8000) controlplane::sse::write_comment(writer, "keepalive");
        }
        controlplane::sse::close(writer); controlplane::metrics::sse_on_close();
      } catch (...) {
        controlplane::sse::write_event(writer, "error", "{\\\"code\\\":\\\"VA_STREAM_ERROR\\\"}");
        controlplane::sse::close(writer); controlplane::metrics::sse_on_close();
      }
      return true;
    }

    // Handle subscription events: /api/subscriptions/{id}/events
    if (path.size() >= 7 && path.rfind("/events") == path.size()-7) {
      // Extract cp_id between /api/subscriptions/ and /events
      std::string cp_id;
      const std::string prefix = "/api/subscriptions/";
      auto p = path.find(prefix);
      if (p != std::string::npos) {
        p += prefix.size();
        auto e = path.rfind("/events");
        if (e != std::string::npos && e > p) cp_id = path.substr(p, e-p);
      }
      // Try to start VA Watch (adapter will stream and close if succeeds)
      std::string werr;
      if (!cp_id.empty() && try_start_va_watch(cfg, cp_id, writer, &werr)) {
        return true;
      }
      // Fallback SSE error
      controlplane::sse::write_headers(writer);
      controlplane::metrics::sse_on_open();
      controlplane::sse::write_event(writer, "error", "{\\\"code\\\":\\\"VA_WATCH_UNAVAILABLE\\\"}");
      controlplane::sse::close(writer);
      controlplane::metrics::sse_on_close();
      controlplane::metrics::inc_request("/api/subscriptions/{id}/events", method, 200);
      return true;
    }
    return false;
  };
  if (!http.start(cfg.http_listen, handler, streamHandler)) {
    std::cerr << "[controlplane] http.start failed" << std::endl; return 1;
  }
  std::cout << "[controlplane] listening on " << cfg.http_listen << std::endl;
  // keep alive
  while (true) std::this_thread::sleep_for(std::chrono::seconds(60));
  return 0;
}
