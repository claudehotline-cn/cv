#pragma once
#include <string>
#include "controlplane/http_server.hpp"
#include "controlplane/config.hpp"

namespace controlplane {

// Try to start VA Watch streaming for a subscription and stream SSE via writer.
// Returns true if the adapter took ownership of the socket and is streaming (writer.close will be called by adapter),
// false if watch is unavailable or failed to start (caller should fallback to error/placeholder).
bool try_start_va_watch(const AppConfig& cfg,
                        const std::string& cp_id,
                        StreamWriter writer,
                        std::string* err);

} // namespace controlplane



