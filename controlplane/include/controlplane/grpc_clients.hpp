#pragma once
#include <string>
#include <vector>
#include <memory>
// Require concrete Stub definitions for nested types
#include "analyzer_control.grpc.pb.h"
#include "source_control.grpc.pb.h"

// Forward declarations for gRPC stubs (global namespace)
namespace va { namespace v1 { class AnalyzerControl; } }
namespace vsm { namespace v1 { class SourceControl; } }

namespace controlplane {

// Lightweight probes
bool quick_probe_va(const std::string& addr);
bool quick_probe_vsm(const std::string& addr);

// Initialize TLS options from app config; call once at startup
struct AppConfig; // fwd
void init_grpc_tls_from_config(const AppConfig& cfg);

// Get last observed gRPC status code from a client call (thread-local).
// Returns -1 if no call has been made in this thread.
int last_grpc_status_code();

// Set last observed gRPC status code for the current thread (helpers for direct stub usage)
void set_last_grpc_status_code(int code);

// VA subscription RPCs
bool va_subscribe(const std::string& addr,
                  const std::string& stream_id,
                  const std::string& profile,
                  const std::string& source_uri,
                  const std::string& model_id,
                  std::string* subscription_id,
                  std::string* err);

bool va_unsubscribe(const std::string& addr,
                    const std::string& stream_id,
                    const std::string& profile,
                    std::string* err);

// VSM enable/disable via Update(options["enabled"] = "true"/"false")
bool vsm_set_enabled(const std::string& addr,
                     const std::string& attach_id,
                     bool enabled,
                     std::string* err);

// VA control RPCs (minimal surface for M0)
bool va_apply_pipeline(const std::string& addr,
                       const std::string& pipeline_name,
                       const std::string& yaml_path,
                       const std::string& graph_id,
                       const std::string& serialized,
                       const std::string& format,
                       const std::string& revision,
                       std::string* err);

bool va_remove_pipeline(const std::string& addr,
                        const std::string& pipeline_name,
                        std::string* err);

struct ApplyItem {
  std::string pipeline_name;
  std::string yaml_path;
  std::string graph_id;
  std::string serialized;
  std::string format;
  std::string revision;
};

bool va_apply_pipelines(const std::string& addr,
                        const std::vector<ApplyItem>& items,
                        int* accepted,
                        std::vector<std::string>* errors,
                        std::string* err);

bool va_hotswap_model(const std::string& addr,
                      const std::string& pipeline_name,
                      const std::string& node,
                      const std::string& model_uri,
                      std::string* err);

bool va_get_status(const std::string& addr,
                   const std::string& pipeline_name,
                   std::string* phase,
                   std::string* metrics_json,
                   std::string* err);

bool va_drain(const std::string& addr,
              const std::string& pipeline_name,
              int timeout_sec,
              bool* drained,
              std::string* err);

// Triton repository controls (in-process)
bool va_repo_load(const std::string& addr, const std::string& model, std::string* err);
bool va_repo_unload(const std::string& addr, const std::string& model, std::string* err);
bool va_repo_poll(const std::string& addr, std::string* err);
bool va_repo_list(const std::string& addr, std::vector<std::string>* models, std::string* err);

// Helpers to create stubs with configured TLS credentials
std::unique_ptr<::va::v1::AnalyzerControl::Stub> make_va_stub(const std::string& addr);
std::unique_ptr<::vsm::v1::SourceControl::Stub> make_vsm_stub(const std::string& addr);

} // namespace controlplane

