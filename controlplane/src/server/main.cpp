#include <iostream>
#include <string>
#include <thread>
#include <chrono>
#include <sstream>
#include <cstring>
#include <cctype>

#include "controlplane/config.hpp"
#include "controlplane/http_server.hpp"
#include "controlplane/store.hpp"
#include "controlplane/grpc_clients.hpp"
#include "controlplane/watch_adapter.hpp"
#include "controlplane/sse_utils.hpp"
#include "controlplane/metrics.hpp"
#include "controlplane/cache.hpp"

#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "source_control.grpc.pb.h"

namespace controlplane { bool quick_probe_va(const std::string&); bool quick_probe_vsm(const std::string&); }

namespace {
struct ErrMap { int code; const char* text; };
inline ErrMap cp_map_err(const std::string& emsg) {
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
  std::string cfgDir = "controlplane/config";
  if (argc >= 2) cfgDir = argv[1];

  AppConfig cfg;
  std::string err;
  if (!load_config(cfgDir, &cfg, &err)) {
    std::cerr << "[controlplane] load_config failed: " << err << std::endl;
    return 1;
  }
  std::cout << "[controlplane] listen=" << cfg.http_listen
            << " va=" << cfg.va_addr << " vsm=" << cfg.vsm_addr << std::endl;

  // Quick gRPC probes (best-effort)
  try { quick_probe_va(cfg.va_addr); } catch (...) {}
  try { quick_probe_vsm(cfg.vsm_addr); } catch (...) {}

  // Start HTTP server
  HttpServer http;
  auto handler = [cfg](const std::string& method, const std::string& path, const std::string& headers, const std::string& body) -> HttpResponse {
    HttpResponse r;
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
    // CORS preflight
    if (method == "OPTIONS") {
      r.status = 200;
      r.extraHeaders += "Access-Control-Allow-Methods: GET,POST,DELETE,OPTIONS\r\nAccess-Control-Allow-Headers: Content-Type,Authorization\r\n";
      r.body = "{}"; return r;
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
          r.status = 200; r.body = cached; controlplane::metrics::inc_request("/api/system/info", method, r.status); return r;
        }
      }
      try {
        auto ch = grpc::CreateChannel(cfg.va_addr, grpc::InsecureChannelCredentials());
        auto stub = va::v1::AnalyzerControl::NewStub(ch);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        va::v1::QueryRuntimeRequest req; va::v1::QueryRuntimeReply rep; auto s = stub->QueryRuntime(&ctx, req, &rep);
        if (s.ok()) { provider=rep.provider(); gpu=rep.gpu_active(); iob=rep.io_binding(); }
      } catch (...) {}
      try {
        auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
        auto stub = vsm::v1::SourceControl::NewStub(ch);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(1500));
        vsm::v1::GetHealthRequest req; vsm::v1::GetHealthReply rep; auto s = stub->GetHealth(&ctx, req, &rep);
        if (s.ok()) { vsm_streams = rep.streams_size(); }
      } catch (...) {}
      std::ostringstream os;
      os << "{\"code\":\"OK\",\"data\":{";
      // CP restream config
      os << "\"restream\":{\"rtsp_base\":\"" << cfg.restream_rtsp_base << "\",\"source\":\"config\"},";
      // VA runtime
      os << "\"runtime\":{\"provider\":\""<<provider<<"\",\"gpu_active\":"<<(gpu?"true":"false")<<",\"io_binding\":"<<(iob?"true":"false")<<"},";
      // VSM summary
      os << "\"vsm\":{\"streams\":"<<vsm_streams<<"}";
      os << "}}";
      r.status = 200; r.body = os.str();
      controlplane::cache::SimpleCache::instance().put("system_info", r.body);
      controlplane::metrics::inc_request("/api/system/info", method, r.status);
      return r;
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
            auto getq = [&](const char* key){
              auto k = std::string(key) + "=";
              auto p = qs.find(k);
              if (p==std::string::npos) return std::string("");
              p += k.size();
              auto e = qs.find('&', p);
              auto v = qs.substr(p, e==std::string::npos? std::string::npos : e-p);
              // no url-decode for simplicity in smoke
              return v;
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
        std::string va_id, err;
        if (!va_subscribe(cfg.va_addr, stream_id, profile, source_uri, model_id, &va_id, &err)) {
          auto mm = cp_map_err(err);
          r.status = mm.code; r.body = std::string("{\"code\":\"") + mm.text + "\",\"msg\":\"" + err + "\"}"; return r;
        }
        auto& st = Store::instance();
        auto cp_id = st.create(stream_id, profile, source_uri, model_id, va_id);
        r.status = 202;
        r.extraHeaders = std::string("Location: /api/subscriptions/") + cp_id + "\r\nAccess-Control-Expose-Headers: Location,ETag\r\n";
        r.body = std::string("{\"code\":\"ACCEPTED\",\"id\":\"") + cp_id + "\"}";
        controlplane::metrics::inc_request("/api/subscriptions", method, r.status);
        return r;
      }
      // SSE (events) placeholder: waiting for VA Watch streaming RPC
      if (method == "GET" && path.size() > strlen("/api/subscriptions/") && path.find("/events") == path.size()-7) {
        // e.g., /api/subscriptions/{id}/events
        r.status = 501;
        r.body = "{\"code\":\"VA_WATCH_UNAVAILABLE\",\"msg\":\"SSE requires VA Watch streaming RPC\"}";
        controlplane::metrics::inc_request("/api/subscriptions/{id}/events", method, r.status);
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
        if (not_modified) { r.status = 304; r.body = ""; controlplane::metrics::inc_request("/api/subscriptions/{id}", method, r.status); return r; }
        std::ostringstream os;
        os << "{\"code\":\"OK\",\"data\":{\"id\":\"" << rec->cp_id
           << "\",\"phase\":\"" << rec->last.phase << "\"";
        if (!rec->last.reason.empty()) os << ",\"reason\":\"" << rec->last.reason << "\"";
        os << ",\"pipeline_key\":\"" << rec->va_subscription_id << "\"}}";
        r.status = 200; r.body = os.str(); controlplane::metrics::inc_request("/api/subscriptions/{id}", method, r.status); return r;
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
        r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/subscriptions/{id}", method, r.status); return r;
      }
      r.status = 404; r.body = "{}"; return r;
    }
  if (path == "/metrics") {
      r.contentType = "text/plain; version=0.0.4; charset=utf-8";
      r.body = controlplane::metrics::render_prometheus(); controlplane::metrics::inc_request("/metrics", method, 200); return r;
    }
    // VSM sources endpoints
    if (path == "/api/sources" && method == "GET") {
      // Try WatchState single snapshot; fallback to GetHealth
      // cache: 1.5s TTL
      {
        std::string cached;
        if (controlplane::cache::SimpleCache::instance().get("sources", 1500, &cached)) {
          r.status = 200; r.body = cached; controlplane::metrics::inc_request("/api/sources", method, r.status); return r;
        }
      }
      std::ostringstream os;
      os << "{\"code\":\"OK\",\"data\":{\"items\":[";
      bool first = true;
      bool ok = false;
      try {
        auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
        auto stub = vsm::v1::SourceControl::NewStub(ch);
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
          auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
          auto stub = vsm::v1::SourceControl::NewStub(ch);
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
      os << "]}}";
      r.status = 200; r.body = os.str(); controlplane::cache::SimpleCache::instance().put("sources", r.body); controlplane::metrics::inc_request("/api/sources", method, r.status); return r;
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
      if (attach_id.empty() || source_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/sources:attach", method, r.status); return r; }
      try {
        auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
        auto stub = vsm::v1::SourceControl::NewStub(ch);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000));
        vsm::v1::AttachRequest req; req.set_attach_id(attach_id); req.set_source_uri(source_uri); req.set_pipeline_id(pipeline_id);
        vsm::v1::AttachReply rep; auto s = stub->Attach(&ctx, req, &rep);
        if (!s.ok() || !rep.accepted()) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; controlplane::metrics::inc_request("/api/sources:attach", method, r.status); return r; }
        r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/sources:attach", method, r.status); return r;
      } catch (...) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; controlplane::metrics::inc_request("/api/sources:attach", method, r.status); return r; }
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
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/sources:detach", method, r.status); return r; }
      try {
        auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
        auto stub = vsm::v1::SourceControl::NewStub(ch);
        grpc::ClientContext ctx; ctx.set_deadline(std::chrono::system_clock::now()+std::chrono::milliseconds(5000));
        vsm::v1::DetachRequest req; req.set_attach_id(attach_id);
        vsm::v1::DetachReply rep; auto s = stub->Detach(&ctx, req, &rep);
        if (!s.ok() || !rep.removed()) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; controlplane::metrics::inc_request("/api/sources:detach", method, r.status); return r; }
        r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/sources:detach", method, r.status); return r;
      } catch (...) { r.status=502; r.body="{\"code\":\"BACKEND_ERROR\"}"; controlplane::metrics::inc_request("/api/sources:detach", method, r.status); return r; }
    }
    if (path.rfind("/api/sources:enable",0)==0 && method == "POST") {
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
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/sources:enable", method, r.status); return r; }
      std::string err;
      if (!vsm_set_enabled(cfg.vsm_addr, attach_id, true, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\"}"; controlplane::metrics::inc_request("/api/sources:enable", method, r.status); return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/sources:enable", method, r.status); return r;
    }
    if (path.rfind("/api/sources:disable",0)==0 && method == "POST") {
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
      if (attach_id.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/sources:disable", method, r.status); return r; }
      std::string err;
      if (!vsm_set_enabled(cfg.vsm_addr, attach_id, false, &err)) { auto mm=cp_map_err(err); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\"}"; controlplane::metrics::inc_request("/api/sources:disable", method, r.status); return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/sources:disable", method, r.status); return r;
    }
    // VA control: apply pipeline (M0 minimal)
    if (path.rfind("/api/control/apply_pipeline", 0) == 0 && method == "POST") {
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
      std::string pipeline_name = extract("pipeline_name");
      // spec nested fields: support naive scan as they appear quoted in JSON
      std::string yaml_path = extract("yaml_path");
      std::string graph_id  = extract("graph_id");
      std::string serialized= extract("serialized");
      std::string format    = extract("format");
      std::string revision  = extract("revision");
      if (pipeline_name.empty()) {
        // query string fallback
        auto q = path.find('?');
        if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
          pipeline_name = getq("pipeline_name");
          if (yaml_path.empty()) yaml_path = getq("yaml_path");
          if (graph_id.empty()) graph_id = getq("graph_id");
          if (revision.empty()) revision = getq("revision");
          if (format.empty()) format = getq("format");
        }
      }
      if (pipeline_name.empty() || (yaml_path.empty() && graph_id.empty() && serialized.empty())) {
        r.status = 400; r.body = "{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/apply_pipeline", method, r.status); return r;
      }
      std::string err2;
      if (!va_apply_pipeline(cfg.va_addr, pipeline_name, yaml_path, graph_id, serialized, format, revision, &err2)) {
        auto mm = cp_map_err(err2);
        r.status = mm.code; r.body = std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err2+"\"}"; controlplane::metrics::inc_request("/api/control/apply_pipeline", method, r.status); return r;
      }
      r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/control/apply_pipeline", method, r.status); return r;
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
        pipeline_name = extract("pipeline_name");
      }
      if (pipeline_name.empty()) { r.status = 400; r.body = "{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/pipeline", method, r.status); return r; }
      std::string err3;
      if (!va_remove_pipeline(cfg.va_addr, pipeline_name, &err3)) {
        auto mm = cp_map_err(err3);
        r.status = mm.code; r.body = std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+err3+"\"}"; controlplane::metrics::inc_request("/api/control/pipeline", method, r.status); return r;
      }
      r.status = 202; r.body = "{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/control/pipeline", method, r.status); return r;
    }
    // VA control: batch apply pipelines
    if (path.rfind("/api/control/apply_pipelines", 0) == 0 && method == "POST") {
      std::vector<controlplane::ApplyItem> items;
      size_t pos = 0;
      while (true) {
        auto p = body.find("\"pipeline_name\"", pos); if (p==std::string::npos) break;
        auto c = body.find('"', body.find(':', p)+1); if (c==std::string::npos) break;
        auto d = body.find('"', c+1); if (d==std::string::npos) break;
        controlplane::ApplyItem ai; ai.pipeline_name = body.substr(c+1, d-c-1);
        auto findkv = [&](const char* key, size_t from)->std::string{
          auto kp = body.find(std::string("\"")+key+"\"", from); if (kp==std::string::npos) return std::string();
          kp = body.find(':', kp); if (kp==std::string::npos) return std::string();
          auto q1 = body.find('"', kp+1); if (q1==std::string::npos) return std::string();
          auto q2 = body.find('"', q1+1); if (q2==std::string::npos) return std::string();
          return body.substr(q1+1, q2-q1-1);
        };
        ai.yaml_path = findkv("yaml_path", d);
        ai.graph_id  = findkv("graph_id", d);
        ai.revision  = findkv("revision", d);
        ai.serialized= findkv("serialized", d);
        ai.format    = findkv("format", d);
        items.push_back(std::move(ai));
        pos = d+1;
      }
      if (items.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/apply_pipelines", method, r.status); return r; }
      int accepted = 0; std::vector<std::string> errors; std::string errb;
      if (!va_apply_pipelines(cfg.va_addr, items, &accepted, &errors, &errb)) {
        r.status=502; r.body = "{\"code\":\"BACKEND_ERROR\",\"msg\":\""+errb+"\"}"; controlplane::metrics::inc_request("/api/control/apply_pipelines", method, r.status); return r;
      }
      std::ostringstream os; os << "{\"code\":\"ACCEPTED\",\"accepted\":"<<accepted;
      if (!errors.empty()) { os << ",\"errors\":["; for (size_t i=0;i<errors.size();++i){ if(i) os<<","; os<<"\""<<errors[i]<<"\"";} os<<"]"; }
      os << "}";
      r.status=202; r.body=os.str(); controlplane::metrics::inc_request("/api/control/apply_pipelines", method, r.status); return r;
    }
    // VA control: hotswap model
    if (path.rfind("/api/control/hotswap", 0) == 0 && method == "POST") {
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
      std::string pipeline_name = extract("pipeline_name");
      std::string node = extract("node");
      std::string model_uri = extract("model_uri");
      if (pipeline_name.empty() || node.empty() || model_uri.empty()) {
        auto q = path.find('?'); if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
          if (pipeline_name.empty()) pipeline_name = getq("pipeline_name");
          if (node.empty()) node = getq("node");
          if (model_uri.empty()) model_uri = getq("model_uri");
        }
      }
      if (pipeline_name.empty() || node.empty() || model_uri.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/hotswap", method, r.status); return r; }
      std::string errh; if (!va_hotswap_model(cfg.va_addr, pipeline_name, node, model_uri, &errh)) { auto mm=cp_map_err(errh); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errh+"\"}"; controlplane::metrics::inc_request("/api/control/hotswap", method, r.status); return r; }
      r.status=202; r.body="{\"code\":\"ACCEPTED\"}"; controlplane::metrics::inc_request("/api/control/hotswap", method, r.status); return r;
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
        auto extract = [&](const char* key) {
          auto k = std::string("\"") + key + "\""; auto p = body.find(k); if (p==std::string::npos) return std::string(""); p = body.find(':', p); if (p==std::string::npos) return std::string(""); auto q1 = body.find('"', p+1); if (q1==std::string::npos) return std::string(""); auto q2 = body.find('"', q1+1); if (q2==std::string::npos) return std::string(""); return body.substr(q1+1, q2-q1-1);
        };
        pipeline_name = extract("pipeline_name");
      }
      if (pipeline_name.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/status", method, r.status); return r; }
      std::string phase, metrics_json, errs;
      if (!va_get_status(cfg.va_addr, pipeline_name, &phase, &metrics_json, &errs)) { auto mm=cp_map_err(errs); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+errs+"\"}"; controlplane::metrics::inc_request("/api/control/status", method, r.status); return r; }
      std::ostringstream os; os << "{\"code\":\"OK\",\"data\":{\"pipeline_name\":\""<<pipeline_name<<"\",\"phase\":\""<<phase<<"\""; if(!metrics_json.empty()){ os<<",\"metrics\":"<<metrics_json; } os << "}}";
      r.status=200; r.body=os.str(); controlplane::metrics::inc_request("/api/control/status", method, r.status); return r;
    }
    // VA control: drain pipeline
    if (path.rfind("/api/control/drain", 0) == 0 && method == "POST") {
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
      auto extract_num = [&](const char* key)->int{
        auto k = std::string("\"") + key + "\""; auto p = body.find(k); if (p==std::string::npos) return 0; p = body.find(':', p); if (p==std::string::npos) return 0; size_t i = p+1; while(i<body.size() && (body[i]==' '||body[i]=='\t')) ++i; size_t j=i; while(j<body.size() && std::isdigit(static_cast<unsigned char>(body[j]))) ++j; if (j==i) return 0; try{ return std::stoi(body.substr(i, j-i)); } catch(...) { return 0; }
      };
      std::string pipeline_name = extract("pipeline_name");
      int timeout_sec = extract_num("timeout_sec");
      if (pipeline_name.empty()) {
        auto q = path.find('?'); if (q != std::string::npos) {
          auto qs = path.substr(q+1);
          auto getq = [&](const char* key){ auto k=std::string(key)+"="; auto p=qs.find(k); if(p==std::string::npos) return std::string(""); p+=k.size(); auto e=qs.find('&',p); return qs.substr(p, e==std::string::npos? std::string::npos : e-p); };
          pipeline_name = getq("pipeline_name");
          auto ts = getq("timeout_sec"); if (!ts.empty()) { try { timeout_sec = std::stoi(ts); } catch(...) {} }
        }
      }
      if (pipeline_name.empty()) { r.status=400; r.body="{\"code\":\"INVALID_ARGUMENT\"}"; controlplane::metrics::inc_request("/api/control/drain", method, r.status); return r; }
      bool drained=false; std::string erd; if (!va_drain(cfg.va_addr, pipeline_name, timeout_sec, &drained, &erd)) { auto mm=cp_map_err(erd); r.status=mm.code; r.body=std::string("{\"code\":\"")+mm.text+"\",\"msg\":\""+erd+"\"}"; controlplane::metrics::inc_request("/api/control/drain", method, r.status); return r; }
      r.status=202; r.body = std::string("{\"code\":\"ACCEPTED\",\"drained\":") + (drained?"true":"false") + "}"; controlplane::metrics::inc_request("/api/control/drain", method, r.status); return r;
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
        auto ch = grpc::CreateChannel(cfg.vsm_addr, grpc::InsecureChannelCredentials());
        auto stub = vsm::v1::SourceControl::NewStub(ch);
        grpc::ClientContext ctx;
        vsm::v1::WatchStateRequest req; req.set_interval_ms(1000);
        std::unique_ptr< grpc::ClientReader<vsm::v1::WatchStateReply> > reader(stub->WatchState(&ctx, req));
        if (!reader) throw std::runtime_error("VSM WatchState reader null");
        controlplane::sse::write_headers(writer);
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
        if (nowms() - last_keep > 5000) controlplane::sse::write_comment(writer, "keepalive");
        controlplane::sse::close(writer);
        try { reader->Finish(); } catch (...) {}
        return true;
      } catch (...) {
        controlplane::sse::write_headers(writer);
        controlplane::metrics::inc_request("/api/sources/watch_sse", method, 200);
        controlplane::sse::write_event(writer, "state", "{\\\"items\\\":[],\\\"error\\\":\\\"VSM_WATCH_UNAVAILABLE\\\"}");
        controlplane::sse::close(writer);
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
      controlplane::sse::write_event(writer, "error", "{\\\"code\\\":\\\"VA_WATCH_UNAVAILABLE\\\"}");
      controlplane::sse::close(writer);
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


