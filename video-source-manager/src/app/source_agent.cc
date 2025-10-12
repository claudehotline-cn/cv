#include "app/source_agent.h"
#include "app/controller/source_controller.h"
#include "app/rpc/grpc_server.h"
#include "app/metrics/metrics_exporter.h"
#include "app/rest/rest_server.h"
#include <sstream>
#include <string>

namespace vsm {

SourceAgent::SourceAgent() = default;
SourceAgent::~SourceAgent() { Stop(); }

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
    return out.str();
  });
  metrics_->Start();
  // REST server
  int rest_port = 7071; if (const char* p = std::getenv("VSM_REST_PORT")) { try { int v=std::stoi(p); if (v>0 && v<65536) rest_port = v; } catch(...){} }
  auto handler = [this](const std::string& method, const std::string& path,
                        const std::unordered_map<std::string,std::string>& query,
                        const std::string& body, int* status, std::string* ctype) -> std::string {
    (void)body; (void)ctype;
    auto ok = [&](const std::string& data){ *status=200; return std::string("{\"success\":true,\"data\":")+data+"}"; };
    auto err = [&](int st, const std::string& msg){ *status=st; return std::string("{\"success\":false,\"message\":\"")+vsm::rest::jsonEscape(msg)+"\"}"; };
    if (method=="GET" && (path=="/api/source/list")) {
      auto vec = controller_->Collect();
      std::ostringstream o; o<<"["; bool first=true; for (auto& s: vec){ if(!first)o<<","; first=false; o<<"{\"id\":\""<<vsm::rest::jsonEscape(s.attach_id)<<"\",\"uri\":\""<<vsm::rest::jsonEscape(s.source_uri)<<"\",\"profile\":\""<<vsm::rest::jsonEscape(s.profile)<<"\",\"model_id\":\""<<vsm::rest::jsonEscape(s.model_id)<<"\",\"fps\":"<<s.fps<<",\"phase\":\""<<s.phase<<"\"}"; }
      o<<"]"; return ok(o.str());
    }
    if (method=="GET" && (path=="/api/source/describe" || path=="/api/source/health")) {
      auto it = query.find("id"); if (it==query.end()||it->second.empty()) return err(400, "missing id");
      vsm::StreamStat st; if(!controller_->GetOne(it->second, &st)) return err(404, "not found");
      std::ostringstream o; o<<"{\"id\":\""<<vsm::rest::jsonEscape(st.attach_id)<<"\",\"uri\":\""<<vsm::rest::jsonEscape(st.source_uri)<<"\",\"profile\":\""<<vsm::rest::jsonEscape(st.profile)<<"\",\"model_id\":\""<<vsm::rest::jsonEscape(st.model_id)<<"\",\"fps\":"<<st.fps<<",\"jitter_ms\":"<<st.jitter_ms<<",\"rtt_ms\":"<<st.rtt_ms<<",\"loss_ratio\":"<<st.loss_pct<<",\"last_ok_unixts\":"<<st.last_ok_unixts<<",\"phase\":\""<<st.phase<<"\"}"; 
      return ok(o.str());
    }
    if (method=="POST" && path=="/api/source/add") {
      auto id_it = query.find("id"); auto uri_it = query.find("uri"); if (id_it==query.end()||uri_it==query.end()) return err(400, "missing id/uri");
      std::unordered_map<std::string,std::string> opt; if (auto p=query.find("profile"); p!=query.end()) opt["profile"] = p->second; if (auto m=query.find("model_id"); m!=query.end()) opt["model_id"]=m->second;
      std::string e; if (!controller_->Attach(id_it->second, uri_it->second, "", opt, &e)) return err(400, e);
      return ok("{}");
    }
    if (method=="POST" && path=="/api/source/update") {
      auto id_it = query.find("id"); if (id_it==query.end()) return err(400, "missing id");
      std::unordered_map<std::string,std::string> opt; if (auto p=query.find("profile"); p!=query.end()) opt["profile"] = p->second; if (auto m=query.find("model_id"); m!=query.end()) opt["model_id"]=m->second;
      std::string e; if (!controller_->Update(id_it->second, opt, &e)) return err(400, e);
      return ok("{}");
    }
    if (method=="POST" && path=="/api/source/delete") {
      auto id_it = query.find("id"); if (id_it==query.end()) return err(400, "missing id");
      std::string e; if (!controller_->Detach(id_it->second, &e)) return err(404, "not found");
      return ok("{}");
    }
    if (method=="GET" && path=="/api/source/watch") {
      uint64_t since = 0; if (auto it=query.find("since"); it!=query.end()) { try { since = std::stoull(it->second); } catch(...){} }
      int timeout_ms = 25000; if (auto it=query.find("timeout_ms"); it!=query.end()) { try { timeout_ms = std::stoi(it->second); } catch(...){} }
      bool full = false; if (auto it=query.find("full"); it!=query.end()) { full = (it->second=="1"||it->second=="true"); }
      uint64_t new_rev = since;
      bool changed = controller_->WaitForChange(since, timeout_ms, &new_rev);
      if (!changed && !full) {
        std::ostringstream o; o<<"{\"rev\":"<<new_rev<<",\"items\":[]}"; return ok(o.str());
      }
      auto snap = controller_->Snapshot();
      std::ostringstream o; o<<"{\"rev\":"<<snap.first<<",\"items\":";
      o<<"["; bool first=true; for (auto& s: snap.second){ if(!first)o<<","; first=false; o<<"{\"id\":\""<<vsm::rest::jsonEscape(s.attach_id)<<"\",\"uri\":\""<<vsm::rest::jsonEscape(s.source_uri)<<"\",\"profile\":\""<<vsm::rest::jsonEscape(s.profile)<<"\",\"model_id\":\""<<vsm::rest::jsonEscape(s.model_id)<<"\",\"fps\":"<<s.fps<<",\"phase\":\""<<s.phase<<"\"}"; } o<<"]}";
      return ok(o.str());
    }
    *status = 404; return "{}";
  };
  static std::unique_ptr<vsm::rest::RestServer> rest_server;
  rest_server = std::make_unique<vsm::rest::RestServer>(rest_port, handler);
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
