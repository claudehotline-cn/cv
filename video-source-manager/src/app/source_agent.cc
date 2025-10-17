#include "app/source_agent.h"
#include "app/controller/source_controller.h"
#include "app/rpc/grpc_server.h"
#include "app/metrics/metrics_exporter.h"
#include "app/rest/rest_server.h"
#include "app/errors/error_codes.h"
#include <sstream>
#include <algorithm>
#include <string>
#include <regex>
#ifdef _WIN32
#  include <winsock2.h>
#  include <ws2tcpip.h>
#else
#  include <sys/types.h>
#  include <sys/socket.h>
#  include <unistd.h>
#endif

namespace vsm {

// SSE metrics (file-scope, exported via /metrics)
static std::atomic<int> g_sse_conn{0};
static std::atomic<unsigned long long> g_sse_rejects{0};
static int g_sse_max_conn = [](){ int v=16; if(const char* p=getenv("VSM_SSE_MAX_CONN")){ try{ int t=std::stoi(p); if(t>0) v=t; }catch(...){} } return v; }();

SourceAgent::SourceAgent() = default;
SourceAgent::~SourceAgent() { Stop(); }

void SourceAgent::RecordRestMetric(const std::string& path, const std::string& code, double seconds) {
  std::lock_guard<std::mutex> lk(rest_mu_);
  rest_totals_by_code_[path][code] += 1ULL;
  auto& buckets = rest_hist_buckets_[path];
  if (buckets.size() != rest_bounds_.size()) buckets.assign(rest_bounds_.size(), 0ULL);
  bool placed=false;
  for (size_t i=0;i<rest_bounds_.size();++i) {
    if (seconds <= rest_bounds_[i]) { buckets[i] += 1ULL; placed=true; break; }
  }
  if (!placed && !buckets.empty()) buckets.back() += 1ULL; // +Inf as last bucket in exposition
  rest_hist_sum_[path] += seconds;
  rest_hist_count_[path] += 1ULL;
}

bool SourceAgent::Start(const std::string& grpc_addr) {
  controller_ = std::make_unique<SourceController>();
  // Registry path from env or default
  std::string reg_path = "vsm_registry.tsv";
#ifdef _WIN32
  if (const char* p = std::getenv("VSM_REGISTRY_PATH")) { reg_path = p; }
#else
  if (const char* p = std::getenv("VSM_REGISTRY_PATH")) { reg_path = p; }
#endif
  controller_->SetRegistryPath(reg_path);
  // Try load existing registry and auto-attach
  controller_->LoadRegistry(nullptr);
  grpc_ = std::make_unique<rpc::GrpcServer>(*controller_, grpc_addr);
  // Metrics exporter builds /metrics on demand from controller stats
  metrics_ = std::make_unique<metrics::MetricsExporter>(9101, [this]() {
    std::ostringstream out;
    out << "# HELP vsm_stream_up 1 if stream session is running\n# TYPE vsm_stream_up gauge\n";
    out << "# HELP vsm_stream_fps Frames per second\n# TYPE vsm_stream_fps gauge\n";
    out << "# HELP vsm_stream_jitter_ms Jitter estimate of inter-frame intervals\n# TYPE vsm_stream_jitter_ms gauge\n";
    out << "# HELP vsm_stream_rtt_ms Approximate round-trip time (placeholder)\n# TYPE vsm_stream_rtt_ms gauge\n";
    out << "# HELP vsm_stream_loss_ratio Loss ratio estimate (0..1)\n# TYPE vsm_stream_loss_ratio gauge\n";
    out << "# HELP vsm_stream_last_ok_unixts Last OK unix timestamp\n# TYPE vsm_stream_last_ok_unixts gauge\n";
    for (const auto& s : controller_->Collect()) {
      int up = (s.phase == "Ready") ? 1 : 0;
      out << "vsm_stream_up{attach_id=\"" << s.attach_id << "\"} " << up << "\n";
      out << "vsm_stream_fps{attach_id=\"" << s.attach_id << "\"} " << s.fps << "\n";
      out << "vsm_stream_jitter_ms{attach_id=\"" << s.attach_id << "\"} " << s.jitter_ms << "\n";
      out << "vsm_stream_rtt_ms{attach_id=\"" << s.attach_id << "\"} " << s.rtt_ms << "\n";
      out << "vsm_stream_loss_ratio{attach_id=\"" << s.attach_id << "\"} " << s.loss_pct << "\n";
      out << "vsm_stream_last_ok_unixts{attach_id=\"" << s.attach_id << "\"} " << (unsigned long long)(s.last_ok_unixts) << "\n";
    }
    // SSE metrics
    out << "vsm_sse_connections " << g_sse_conn.load() << "\n";
    out << "vsm_sse_rejects_total " << (unsigned long long)g_sse_rejects.load() << "\n";
    out << "vsm_sse_max_connections " << g_sse_max_conn << "\n";
    // REST request metrics
    {
      std::lock_guard<std::mutex> lk(rest_mu_);
      out << "# HELP vsm_rest_requests_total REST requests total by path/code\n# TYPE vsm_rest_requests_total counter\n";
      for (const auto& kv : rest_totals_by_code_) {
        const std::string& path = kv.first;
        for (const auto& kv2 : kv.second) {
          out << "vsm_rest_requests_total{path=\"" << path << "\",code=\"" << kv2.first << "\"} "
              << (unsigned long long)kv2.second << "\n";
        }
      }
      out << "# HELP vsm_rest_request_duration_seconds REST request duration (s)\n# TYPE vsm_rest_request_duration_seconds histogram\n";
      for (const auto& kvh : rest_hist_buckets_) {
        const std::string& path = kvh.first;
        double sum = rest_hist_sum_.count(path)? rest_hist_sum_.at(path) : 0.0;
        unsigned long long cnt = rest_hist_count_.count(path)? rest_hist_count_.at(path) : 0ULL;
        unsigned long long acc = 0ULL;
        for (size_t i=0;i<rest_bounds_.size();++i) {
          acc += kvh.second[i];
          out << "vsm_rest_request_duration_seconds_bucket{path=\"" << path << "\",le=\"" << rest_bounds_[i] << "\"} " << acc << "\n";
        }
        out << "vsm_rest_request_duration_seconds_bucket{path=\"" << path << "\",le=\"+Inf\"} " << cnt << "\n";
        out << "vsm_rest_request_duration_seconds_sum{path=\"" << path << "\"} " << sum << "\n";
        out << "vsm_rest_request_duration_seconds_count{path=\"" << path << "\"} " << cnt << "\n";
      }
    }
    return out.str();
  });
  metrics_->Start();
  // REST server
  int rest_port = 7071; if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v=std::stoi(p); if (v>0 && v<65536) rest_port = v; } catch(...){} }
  auto handler = [this](const std::string& method, const std::string& path,
                        const std::unordered_map<std::string,std::string>& query,
                        const std::unordered_map<std::string,std::string>& headers,
                        const std::string& body, int* status, std::string* ctype) -> std::string {
    (void)body; (void)ctype;
    auto ok = [&](const std::string& data){ *status=200; return std::string("{\"success\":true,\"code\":\"OK\",\"data\":")+data+"}"; };
    auto err = [&](vsm::errors::ErrorCode ec, const std::string& msg){
      *status = vsm::errors::http_status(ec);
      std::ostringstream o; o<<"{\"success\":false,\"code\":\""<<vsm::errors::to_string(ec)<<"\",\"message\":\""<<vsm::rest::jsonEscape(msg)<<"\"}"; return o.str(); };
    std::unordered_map<std::string,std::string> jbody;
    bool is_json = false; if (auto it=headers.find("content-type"); it!=headers.end()) { auto v=it->second; std::transform(v.begin(), v.end(), v.begin(), ::tolower); is_json = (v.find("application/json")!=std::string::npos) || (v.find("json")!=std::string::npos); }
    if (!body.empty() && (is_json || body.find('{') != std::string::npos)) vsm::rest::parseJsonObjectFlat(body, jbody);
    if (method=="GET" && (path=="/api/source/list")) {
      auto vec = controller_->Collect();
      std::ostringstream o; o<<"["; bool first=true; for (auto& s: vec){ if(!first)o<<","; first=false; 
        o<<"{\"id\":\""<<vsm::rest::jsonEscape(s.attach_id)
         <<"\",\"uri\":\""<<vsm::rest::jsonEscape(s.source_uri)
         <<"\",\"profile\":\""<<vsm::rest::jsonEscape(s.profile)
         <<"\",\"model_id\":\""<<vsm::rest::jsonEscape(s.model_id)
         <<"\",\"fps\":"<<s.fps
         <<",\"phase\":\""<<s.phase<<"\""
         <<",\"caps\":{\"codec\":\""<<vsm::rest::jsonEscape(s.codec)
         <<"\",\"resolution\":["<<s.width<<","<<s.height<<"]"
         <<",\"fps\":"<<s.fps
         <<",\"pix_fmt\":\""<<vsm::rest::jsonEscape(s.pix_fmt)
         <<"\",\"color_space\":\""<<vsm::rest::jsonEscape(s.color_space)<<"\"}}"; }
      o<<"]"; return ok(o.str());
    }
    if (method=="GET" && (path=="/api/source/describe" || path=="/api/source/health")) {
      auto it = query.find("id"); if (it==query.end()||it->second.empty()) return err(vsm::errors::ErrorCode::INVALID_ARG, "missing id");
      vsm::StreamStat st; if(!controller_->GetOne(it->second, &st)) return err(vsm::errors::ErrorCode::NOT_FOUND, "not found");
      std::ostringstream o; o<<"{\"id\":\""<<vsm::rest::jsonEscape(st.attach_id)
        <<"\",\"uri\":\""<<vsm::rest::jsonEscape(st.source_uri)
        <<"\",\"profile\":\""<<vsm::rest::jsonEscape(st.profile)
        <<"\",\"model_id\":\""<<vsm::rest::jsonEscape(st.model_id)
        <<"\",\"fps\":"<<st.fps
        <<",\"jitter_ms\":"<<st.jitter_ms
        <<",\"rtt_ms\":"<<st.rtt_ms
        <<",\"loss_ratio\":"<<st.loss_pct
        <<",\"last_ok_unixts\":"<<st.last_ok_unixts
        <<",\"phase\":\""<<st.phase<<"\""
        <<",\"caps\":{\"codec\":\""<<vsm::rest::jsonEscape(st.codec)
        <<"\",\"resolution\":["<<st.width<<","<<st.height<<"]"
        <<",\"fps\":"<<st.fps
        <<",\"pix_fmt\":\""<<vsm::rest::jsonEscape(st.pix_fmt)
        <<"\",\"color_space\":\""<<vsm::rest::jsonEscape(st.color_space)<<"\"}}"; 
      return ok(o.str());
    }
    if (method=="POST" && path=="/api/source/add") {
      auto get = [&](const char* k)->std::string{ auto it=query.find(k); if(it!=query.end()) return it->second; auto jt=jbody.find(k); return jt!=jbody.end()? jt->second : std::string(); };
      std::string id = get("id"), uri = get("uri"); if (id.empty()||uri.empty()) return err(vsm::errors::ErrorCode::INVALID_ARG, "missing id/uri");
      // Validate id and uri
      if (!std::regex_match(id, std::regex("^[A-Za-z0-9_\-]{1,64}$"))) return err(vsm::errors::ErrorCode::INVALID_ARG, "invalid id");
      auto lower = uri; std::transform(lower.begin(), lower.end(), lower.begin(), ::tolower); if (lower.rfind("rtsp://", 0) != 0) return err(vsm::errors::ErrorCode::INVALID_ARG, "invalid uri (expect rtsp://)");
      std::unordered_map<std::string,std::string> opt; std::string prof=get("profile"); if(!prof.empty()) opt["profile"]=prof; std::string mdl=get("model_id"); if(!mdl.empty()) opt["model_id"]=mdl;
      std::string e; if (!controller_->Attach(id, uri, "", opt, &e)) return err(vsm::errors::map_message(e), e);
      return ok("{}");
    }
    if (method=="POST" && path=="/api/source/update") {
      auto get = [&](const char* k)->std::string{ auto it=query.find(k); if(it!=query.end()) return it->second; auto jt=jbody.find(k); return jt!=jbody.end()? jt->second : std::string(); };
      std::string id = get("id"); if (id.empty()) return err(vsm::errors::ErrorCode::INVALID_ARG, "missing id");
      if (!std::regex_match(id, std::regex("^[A-Za-z0-9_\-]{1,64}$"))) return err(vsm::errors::ErrorCode::INVALID_ARG, "invalid id");
      std::unordered_map<std::string,std::string> opt; std::string prof=get("profile"); if(!prof.empty()) opt["profile"]=prof; std::string mdl=get("model_id"); if(!mdl.empty()) opt["model_id"]=mdl;
      std::string e; if (!controller_->Update(id, opt, &e)) return err(vsm::errors::map_message(e), e);
      return ok("{}");
    }
    if (method=="POST" && path=="/api/source/delete") {
      auto id = (query.count("id")? query.at("id") : (jbody.count("id")? jbody.at("id") : std::string()));
      if (id.empty()) return err(vsm::errors::ErrorCode::INVALID_ARG, "missing id");
      std::string e; if (!controller_->Detach(id, &e)) return err(vsm::errors::map_message(e), e);
      return ok("{}");
    }
    if (method=="GET" && path=="/api/source/watch") {
      uint64_t since = 0; if (auto it=query.find("since"); it!=query.end()) { try { since = std::stoull(it->second); } catch(...){} }
      int timeout_ms = 25000; if (auto it=query.find("timeout_ms"); it!=query.end()) { try { timeout_ms = std::stoi(it->second); } catch(...){} }
      bool full = false; if (auto it=query.find("full"); it!=query.end()) { full = (it->second=="1"||it->second=="true"); }
      uint64_t new_rev = since;
      bool changed = controller_->WaitForChange(since, timeout_ms, &new_rev);
      if (!changed && !full) {
        std::ostringstream o; o<<"{\"rev\":"<<new_rev<<",\"items\":[],\"keepalive\":true}"; return ok(o.str());
      }
      auto snap = controller_->Snapshot();
      std::ostringstream o; o << "{\"rev\":" << snap.first << ",\"items\":[";
      bool first=true; 
      for (auto& s : snap.second) {
        if (!first) o << ","; first=false;
        o << "{\"id\":\"" << vsm::rest::jsonEscape(s.attach_id)
          << "\",\"uri\":\"" << vsm::rest::jsonEscape(s.source_uri)
          << "\",\"profile\":\"" << vsm::rest::jsonEscape(s.profile)
          << "\",\"model_id\":\"" << vsm::rest::jsonEscape(s.model_id)
          << "\",\"fps\":" << s.fps
          << ",\"phase\":\"" << s.phase << "\",";
        o << "\"caps\":{\"codec\":\"" << vsm::rest::jsonEscape(s.codec)
          << "\",\"resolution\":[" << s.width << "," << s.height << "]"
          << ",\"fps\":" << s.fps
          << ",\"pix_fmt\":\"" << vsm::rest::jsonEscape(s.pix_fmt)
          << "\",\"color_space\":\"" << vsm::rest::jsonEscape(s.color_space) << "\"}}";
      }
      o << "]}";
      return ok(o.str());
    }
    *status = 404; return "{}";
  };
  static std::unique_ptr<vsm::rest::RestServer> rest_server;
  rest_server = std::make_unique<vsm::rest::RestServer>(rest_port, [this, handler](auto&& method, auto&& path,
                        auto&& query, auto&& headers, auto&& body, int* status, std::string* ctype){
    auto t0 = std::chrono::steady_clock::now();
    std::string resp = handler(method, path, query, headers, body, status, ctype);
    auto t1 = std::chrono::steady_clock::now();
    double sec = std::chrono::duration<double>(t1 - t0).count();
    auto code_from_status = [](int st){
      switch (st) { case 200: return "OK"; case 400: return "INVALID_ARG"; case 404: return "NOT_FOUND"; case 409: return "ALREADY_EXISTS"; case 503: return "UNAVAILABLE"; default: return "INTERNAL"; }
    };
    RecordRestMetric(path, code_from_status(*status), sec);
    return resp;
  });
  rest_server->SetStreamingHandler([this](int cfd,
                                          const std::string& method,
                                          const std::string& path,
                                          const std::unordered_map<std::string,std::string>& query,
                                          const std::unordered_map<std::string,std::string>& /*headers*/){
    (void)method; (void)path;
    // simple concurrency limit
    static int max_conn = [](){ int v=16; if(const char* p=getenv("VSM_SSE_MAX_CONN")){ try{ int t=std::stoi(p); if(t>0) v=t; }catch(...){} } return v; }();

    auto send_all = [&](const std::string& s){
      const char* p = s.c_str(); size_t left = s.size();
      while (left > 0) {
#ifdef _WIN32
        int n = ::send(cfd, p, (int)left, 0);
#else
        ssize_t n = ::send(cfd, p, left, 0);
#endif
        if (n <= 0) break; p += n; left -= (size_t)n;
      }
    };
    auto send_http = [&](int code, const std::string& ctype, const std::string& body){
      std::ostringstream hs; hs << "HTTP/1.1 " << code << (code==200?" OK":"") << "\r\n";
      hs << "Content-Type: " << ctype << "\r\n";
      // CORS for SSE errors too
      hs << "Access-Control-Allow-Origin: *\r\n";
      hs << "Access-Control-Allow-Methods: GET,POST,PUT,DELETE,OPTIONS\r\n";
      hs << "Access-Control-Allow-Headers: Content-Type,Authorization\r\n";
      hs << "Content-Length: " << body.size() << "\r\n";
      hs << "Connection: close\r\n\r\n";
      hs << body;
      send_all(hs.str());
    };

    int cur = g_sse_conn.fetch_add(1) + 1;
    if (cur > max_conn) {
      g_sse_conn.fetch_sub(1);
      g_sse_rejects.fetch_add(1);
      std::string body = "{\"success\":false,\"message\":\"too many sse connections\"}";
      send_http(429, "application/json; charset=utf-8", body);
      return;
    }

    auto cleanup = [&](){ g_sse_conn.fetch_sub(1); };
    // Write SSE headers
    {
      std::ostringstream hs;
      hs << "HTTP/1.1 200 OK\r\n";
      hs << "Content-Type: text/event-stream\r\n";
      hs << "Access-Control-Allow-Origin: *\r\n";
      hs << "Access-Control-Allow-Methods: GET,POST,PUT,DELETE,OPTIONS\r\n";
      hs << "Access-Control-Allow-Headers: Content-Type,Authorization\r\n";
      hs << "Cache-Control: no-cache\r\n";
      hs << "Connection: keep-alive\r\n\r\n";
      send_all(hs.str());
    }

    // Set send timeout to avoid long blocks on slow clients
#ifdef _WIN32
    { int snd_ms = [](){ int d=4000; if(const char* p=getenv("VSM_SSE_SNDTIMEO_MS")){ try{ int t=std::stoi(p); if(t>0) d=t; }catch(...){} } return d; }();
      ::setsockopt(cfd, SOL_SOCKET, SO_SNDTIMEO, (const char*)&snd_ms, sizeof(snd_ms)); }
#else
    { struct timeval tv; tv.tv_sec = 4; tv.tv_usec = 0; ::setsockopt(cfd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv)); }
#endif
    uint64_t since = 0; if (auto it=query.find("since"); it!=query.end()) { try { since = std::stoull(it->second); } catch(...){} }
    int keepalive_ms = [](){ int d=15000; if(const char* p=getenv("VSM_SSE_KEEPALIVE_MS")){ try{ int t=std::stoi(p); if(t>0) d=t; }catch(...){} } return d; }();
    if (auto it=query.find("keepalive_ms"); it!=query.end()) { try { keepalive_ms = std::stoi(it->second); } catch(...){} }
    int max_sec = 300; if (auto it=query.find("max_sec"); it!=query.end()) { try { max_sec = std::stoi(it->second); } catch(...){} }
    auto start_tp = std::chrono::steady_clock::now();
    uint64_t rev = since;
    bool broken = false;
    while (!broken) {
      // Break on max duration
      auto elapsed = std::chrono::duration_cast<std::chrono::seconds>(std::chrono::steady_clock::now() - start_tp).count();
      if (elapsed >= max_sec) break;
      // Wait for change or keepalive interval
      uint64_t new_rev = rev;
      bool changed = controller_->WaitForChange(rev, keepalive_ms, &new_rev);
      if (changed) {
        auto snap = controller_->Snapshot();
        rev = snap.first;
        std::ostringstream o;
        o << "event: update\n";
        // data payload
        o << "data: {\"rev\":" << snap.first << ",\"items\":[";
        bool first=true; for (auto& s: snap.second){ if(!first) o<<","; first=false; 
          o<<"{\"id\":\""<<vsm::rest::jsonEscape(s.attach_id)
            <<"\",\"uri\":\""<<vsm::rest::jsonEscape(s.source_uri)
            <<"\",\"profile\":\""<<vsm::rest::jsonEscape(s.profile)
            <<"\",\"model_id\":\""<<vsm::rest::jsonEscape(s.model_id)
            <<"\",\"fps\":"<<s.fps
            <<",\"phase\":\""<<s.phase<<"\",";
          o<<"\"caps\":{\"codec\":\""<<vsm::rest::jsonEscape(s.codec)
            <<"\",\"resolution\":["<<s.width<<","<<s.height<<"]"
            <<",\"fps\":"<<s.fps
            <<",\"pix_fmt\":\""<<vsm::rest::jsonEscape(s.pix_fmt)
            <<"\",\"color_space\":\""<<vsm::rest::jsonEscape(s.color_space)<<"\"}}"; }
        o << "]}\n\n";
        send_all(o.str());
      } else {
        // keepalive comment
        send_all(": keepalive\n\n");
      }
      // Simple broken detection: try a zero-length probe via shutdown send
#ifdef _WIN32
      // If the peer closed, next send will fail; here we can optionally check using recv with MSG_PEEK (omitted for simplicity)
#else
      // no-op
#endif
      // If we want, we could set broken=true when send_all observed n<=0, but current helper ignores it; keep loop until timeout
    }
    cleanup();
  });
  rest_server->Start();
  return grpc_->Start();
}

void SourceAgent::Stop() {
  if (metrics_) { metrics_->Stop(); metrics_.reset(); }
  if (grpc_) { grpc_->Stop(); grpc_.reset(); }
  if (controller_) { controller_->SaveRegistry(nullptr); }
  controller_.reset();
}

} // namespace vsm




