#include "core/source_reconnects.hpp"

#include <unordered_map>

namespace va::core::SourceReconnects {

namespace {
std::mutex g_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id
std::unordered_map<std::string, uint64_t> g_reconnects; // source_id -> count

uint64_t& ensure(const std::string& sid) {
    auto it = g_reconnects.find(sid);
    if (it == g_reconnects.end()) {
        auto [iter,_] = g_reconnects.emplace(sid, 0ull);
        it = iter;
    }
    return it->second;
}
}

void mapUriToSourceId(const std::string& uri, const std::string& source_id) {
    std::lock_guard<std::mutex> lk(g_mutex);
    g_uri_to_source[uri] = source_id;
}

void unmapUri(const std::string& uri) {
    std::lock_guard<std::mutex> lk(g_mutex);
    g_uri_to_source.erase(uri);
}

void increment(const std::string& source_id, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    ensure(source_id) += n;
}

void incrementByUri(const std::string& uri, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_uri_to_source.find(uri);
    if (it != g_uri_to_source.end()) {
        ensure(it->second) += n;
    }
}

std::vector<Row> snapshot() {
    std::lock_guard<std::mutex> lk(g_mutex);
    std::vector<Row> rows;
    rows.reserve(g_reconnects.size());
    for (auto& kv : g_reconnects) {
        Row r; r.source_id = kv.first; r.reconnects = kv.second;
        rows.emplace_back(std::move(r));
    }
    return rows;
}

} // namespace va::core::SourceReconnects
