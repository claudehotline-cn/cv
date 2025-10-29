#pragma once
#include <string>
#include "controlplane/http_server.hpp"

namespace controlplane {

// HTTP/1.1 proxy helper for WHEP (POST/PATCH/DELETE).
// - Forwards essential headers (Authorization/Accept/Content-Type/If-Match)
// - Forces Accept-Encoding: identity, Connection: close
// - Handles Transfer-Encoding: chunked (de-chunk)
// - Parses and rewrites Location to CP-relative
// Returns true on success and fills out response/body/contentType/status.
bool proxy_http_simple(const std::string& host,
                       int port,
                       const std::string& method,
                       const std::string& path_and_query,
                       const std::string& in_headers,
                       const std::string& body,
                       HttpResponse* out,
                       std::string* out_location);

} // namespace controlplane
