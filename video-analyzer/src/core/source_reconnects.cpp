#include "core/source_reconnects.hpp"

#include <unordered_map>

namespace va::core::SourceReconnects {

namespace {
std::mutex g_uri_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id

struct Shard {
    std::mutex mtx;
    std::unordered_map<std::string, uint64_t> by_source;
};

constexpr size_t kNumShards = 16;
static Shard g_shards[kNumShards];

static inline size_t shard_of(const std::string& sid) {
    return std::hash<std::string>{}(sid) & (kNumShards - 1);
}

uint64_t& ensure_locked(Shard& sh, const std::string& sid) {
    auto it = sh.by_source.find(sid);
    if (it == sh.by_source.end()) {
        it = sh.by_source.try_emplace(sid, 0ull).first;
    }
    return it->second;
}
}

void mapUriToSourceId(const std::string& uri, const std::string& source_id) {
    std::lock_guard<std::mutex> lk(g_uri_mutex);
    g_uri_to_source[uri] = source_id;
}

void unmapUri(const std::string& uri) {
    std::lock_guard<std::mutex> lk(g_uri_mutex);
    g_uri_to_source.erase(uri);
}

void increment(const std::string& source_id, uint64_t n) {
    Shard& sh = g_shards[shard_of(source_id)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    ensure_locked(sh, source_id) += n;
}

void incrementByUri(const std::string& uri, uint64_t n) {
    std::string sid;
    {
        std::lock_guard<std::mutex> lk(g_uri_mutex);
        auto it = g_uri_to_source.find(uri);
        if (it != g_uri_to_source.end()) sid = it->second;
    }
    if (sid.empty()) return;
    Shard& sh = g_shards[shard_of(sid)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    ensure_locked(sh, sid) += n;
}

std::vector<Row> snapshot() {
    std::vector<Row> rows;
    for (size_t i=0;i<kNumShards;++i) {
        Shard& sh = g_shards[i];
        std::lock_guard<std::mutex> lk(sh.mtx);
        rows.reserve(rows.size() + sh.by_source.size());
        for (auto& kv : sh.by_source) {
            Row r; r.source_id = kv.first; r.reconnects = kv.second;
            rows.emplace_back(std::move(r));
        }
    }
    return rows;
}

} // namespace va::core::SourceReconnects
