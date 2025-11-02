#include "controlplane/watch_adapter.hpp"
#include "controlplane/sse_utils.hpp"
#include "controlplane/events.hpp"
#include "controlplane/store.hpp"
#include <string>
#include <thread>
#include <chrono>
#include <cstdlib>
#include <grpcpp/grpcpp.h>
#include "analyzer_control.grpc.pb.h"
#include "controlplane/grpc_clients.hpp"

namespace controlplane {

using namespace std::chrono_literals;

static long long now_ms() {
  using namespace std::chrono; return duration_cast<milliseconds>(system_clock::now().time_since_epoch()).count();
}

bool try_start_va_watch(const AppConfig& cfg, const std::string& cp_id, StreamWriter writer, std::string* err) {
  const char* fake = std::getenv("CP_FAKE_WATCH");
  if (fake && std::string(fake) == "1") {
    // Demo SSE stream: pending -> preparing -> ready
    controlplane::sse::write_headers(writer);
    controlplane::events::PhaseEvent e;
    e.id = cp_id; e.ts_ms = now_ms(); e.phase = "pending";
    controlplane::sse::write_event(writer, "phase", controlplane::events::to_json(e));
    std::this_thread::sleep_for(300ms);
    e.ts_ms = now_ms(); e.phase = "preparing";
    controlplane::sse::write_event(writer, "phase", controlplane::events::to_json(e));
    std::this_thread::sleep_for(300ms);
    e.ts_ms = now_ms(); e.phase = "ready";
    controlplane::sse::write_event(writer, "phase", controlplane::events::to_json(e));
    controlplane::sse::write_comment(writer, "done");
    controlplane::sse::close(writer);
    return true;
  }

  // Lookup cp_id -> VA subscription_id (pipeline key)
  auto rec = Store::instance().get(cp_id);
  if (!rec) { if (err) *err = "cp_id not found"; return false; }
  std::string subscription_id = rec->va_subscription_id;
  if (subscription_id.empty()) { if (err) *err = "empty subscription_id"; return false; }

  // Start gRPC Watch
  try {
    auto stub = controlplane::make_va_stub(cfg.va_addr);
    grpc::ClientContext ctx;
    // Optional deadline from config
    if (cfg.sse.idle_close_ms > 0) {
      ctx.set_deadline(std::chrono::system_clock::now() + std::chrono::milliseconds(cfg.sse.idle_close_ms));
    }

    va::v1::WatchRequest req; req.set_subscription_id(subscription_id);
    std::unique_ptr< grpc::ClientReader<va::v1::PhaseEvent> > reader(stub->Watch(&ctx, req));
    if (!reader) { if (err) *err = "watch reader null"; return false; }

    // Start SSE
    controlplane::sse::write_headers(writer);

    va::v1::PhaseEvent pev;
    long long last_keep = now_ms();
    const long long keepalive_interval_ms = cfg.sse.keepalive_ms > 0 ? cfg.sse.keepalive_ms : 10000;
    while (reader->Read(&pev)) {
      // Map VA event to CP SSE (use cp_id for id)
      controlplane::events::PhaseEvent e;
      e.id = cp_id;
      e.ts_ms = pev.ts_ms();
      e.phase = pev.phase();
      e.reason = pev.reason();
      controlplane::sse::write_event(writer, "phase", controlplane::events::to_json(e));
      last_keep = now_ms();
      if (e.phase == "ready" || e.phase == "failed" || e.phase == "cancelled") {
        break; // terminal
      }
    }
    // If stream ends without terminal, send a keepalive comment and close
    long long now = now_ms();
    if (now - last_keep >= keepalive_interval_ms) {
      controlplane::sse::write_comment(writer, "keepalive");
    }
    controlplane::sse::close(writer);
    // Finish status (ignore errors for SSE completion)
    reader->Finish();
    return true;
  } catch (const std::exception& e) {
    if (err) *err = e.what();
    return false;
  } catch (...) {
    if (err) *err = "unknown exception";
    return false;
  }
}

} // namespace controlplane

