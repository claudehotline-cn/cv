#pragma once
#include <string>
#include "controlplane/http_server.hpp"

namespace controlplane {

// Very small HTTP 1.1 proxy helper for POST/PATCH/DELETE to VA REST (WHEP).
// Connects to host:port, forwards method/path/body with minimal headers,
// parses status/content-type/Location and body. Returns true on success.
bool proxy_http_simple(const std::string& host,
                       int port,
                       const std::string& method,
                       const std::string& path_and_query,
                       const std::string& in_headers,
                       const std::string& body,
                       HttpResponse* out,
                       std::string* out_location);

} // namespace controlplane

