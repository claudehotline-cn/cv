#include "core/nvdec_events.hpp"

namespace va::core::NvdecEvents {

namespace {
std::mutex g_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id
struct Stats { uint64_t recover{0}; uint64_t await_idr{0}; };
std::unordered_map<std::string, Stats> g_stats; // source_id -> stats

Stats& ensure(const std::string& sid) {
    auto it = g_stats.find(sid);
    if (it == g_stats.end()) {
        auto [iter, _] = g_stats.emplace(sid, Stats{});
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
    ensure(source_id).recover += n;
}

void incrementRecoverByUri(const std::string& uri, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_uri_to_source.find(uri);
    if (it != g_uri_to_source.end()) {
        ensure(it->second).recover += n;
    }
}

void incrementAwaitIdr(const std::string& source_id, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    ensure(source_id).await_idr += n;
}

void incrementAwaitIdrByUri(const std::string& uri, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_uri_to_source.find(uri);
    if (it != g_uri_to_source.end()) {
        ensure(it->second).await_idr += n;
    }
}

std::vector<Row> snapshot() {
    std::lock_guard<std::mutex> lk(g_mutex);
    std::vector<Row> rows;
    rows.reserve(g_stats.size());
    for (auto& kv : g_stats) {
        Row r; r.source_id = kv.first; r.device_recover = kv.second.recover; r.await_idr = kv.second.await_idr;
        rows.emplace_back(std::move(r));
    }
    return rows;
}

} // namespace va::core::NvdecEvents
