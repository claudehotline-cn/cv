#include "core/nvdec_events.hpp"

namespace va::core::NvdecEvents {

namespace {
std::mutex g_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id
std::unordered_map<std::string, uint64_t> g_recover; // source_id -> count

uint64_t& ensure(const std::string& sid) {
    auto it = g_recover.find(sid);
    if (it == g_recover.end()) {
        auto [iter, _] = g_recover.emplace(sid, 0ull);
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

void incrementRecover(const std::string& source_id, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    ensure(source_id) += n;
}

void incrementRecoverByUri(const std::string& uri, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_uri_to_source.find(uri);
    if (it != g_uri_to_source.end()) {
        ensure(it->second) += n;
    }
}

std::vector<Row> snapshot() {
    std::lock_guard<std::mutex> lk(g_mutex);
    std::vector<Row> rows;
    rows.reserve(g_recover.size());
    for (auto& kv : g_recover) {
        Row r; r.source_id = kv.first; r.device_recover = kv.second;
        rows.emplace_back(std::move(r));
    }
    return rows;
}

} // namespace va::core::NvdecEvents

