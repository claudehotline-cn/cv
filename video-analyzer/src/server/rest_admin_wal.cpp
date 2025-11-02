#include "server/rest_impl.hpp"

namespace va::server {

HttpResponse RestServer::Impl::handleWalSummary(const HttpRequest& /*req*/) {
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    bool en = false;
    std::uint64_t failed = 0;
    try { en = va::core::wal::enabled(); } catch (...) {}
    try { failed = va::core::wal::failedRestartCount(); } catch (...) {}
    data["enabled"] = en;
    data["failed_restart"] = static_cast<Json::UInt64>(failed);
    payload["data"] = data;
    return jsonResponse(payload, 200);
}

HttpResponse RestServer::Impl::handleWalTail(const HttpRequest& req) {
    auto kv = parseQueryKV(req.query);
    int n = 200;
    if (auto it = kv.find("n"); it != kv.end()) {
        try { n = std::stoi(it->second); } catch (...) {}
    }
    if (n <= 0) n = 1; if (n > 1000) n = 1000; // clamp
    std::vector<std::string> lines;
    try { lines = va::core::wal::tail(static_cast<std::size_t>(n)); } catch (...) { lines.clear(); }
    Json::Value payload = successPayload();
    Json::Value data(Json::objectValue);
    Json::Value arr(Json::arrayValue);
    for (const auto& s : lines) arr.append(s);
    data["items"] = arr;
    data["count"] = static_cast<Json::UInt64>(arr.size());
    payload["data"] = data;
    return jsonResponse(payload, 200);
}

} // namespace va::server

