#include <iostream>
#include "controlplane/db.hpp"
#include <string>
#include <thread>
#include <chrono>
#include <sstream>
#include <cstring>
#include <cctype>
#include <cstdlib>
#include <nlohmann/json.hpp>

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
      r.extraHeaders += "Access-Control-Allow-Methods: GET,POST,DELETE,OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type,Authorization\r\n";
      r.body = "{}"; emit("OPTIONS", r.status); return r;
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
      // SFU/WHEP endpoint for negotiation: point to CP base explicitly
      os << "\"sfu\":{\"whep_base\":\"http://127.0.0.1:18080\"},";
      // VA runtime
      os << "\"runtime\":{\"provider\":\""<<provider<<"\",\"gpu_active\":"<<(gpu?"true":"false")<<",\"io_binding\":"<<(iob?"true":"false")<<"},";
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
      std::string arr;
      if (controlplane::db::list_models_json(cfg, &arr)) {
        r.status = 200; r.body = std::string("{\"code\":\"OK\",\"data\":") + arr + "}";
      } else {
        r.status = 200; r.body = "{\"code\":\"OK\",\"data\":[]}";
      }
      emit("/api/models", r.status); return r;
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
        r.extraHeaders = std::string("Location: /api/subscriptions/") + cp_id + "\r\nAccess-Control-Expose-Headers: Location,ETag\r\n";
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
      if (method == "GET" && (pos = path.find_last_of('/')) != std::string::npos && pos+1 < path.size()) {
        auto cp_id = path.substr(pos+1);
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

        std::ostringstream os;
        os << "{\"code\":\"OK\",\"data\":{\"id\":\"" << rec->cp_id
           << "\",\"phase\":\"" << phase << "\"";
        if (!reason.empty()) os << ",\"reason\":\"" << reason << "\"";
        os << ",\"pipeline_key\":\"" << rec->va_subscription_id << "\"}}";
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


