#include "core/nvdec_events.hpp"
#include <atomic>
#include "core/utils.hpp"

namespace va::core::NvdecEvents {

namespace {
std::mutex g_uri_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id
struct Stats { uint64_t recover{0}; uint64_t await_idr{0}; };
std::atomic<int> g_ttl_seconds{300}; // <=0 disables TTL pruning

struct Shard {
    std::mutex mtx;
    struct Node { Stats stats; double last_seen_ms{0.0}; };
    std::unordered_map<std::string, Node> by_source;
};

constexpr size_t kNumShards = 16;
static Shard g_shards[kNumShards];

static inline size_t shard_of(const std::string& sid) {
    return std::hash<std::string>{}(sid) & (kNumShards - 1);
}

Shard::Node& ensure_locked(Shard& sh, const std::string& sid) {
    auto it = sh.by_source.find(sid);
    if (it == sh.by_source.end()) {
        it = sh.by_source.try_emplace(sid, Shard::Node{}).first;
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

void incrementRecover(const std::string& source_id, uint64_t n) {
    Shard& sh = g_shards[shard_of(source_id)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    auto& node = ensure_locked(sh, source_id);
    node.last_seen_ms = va::core::ms_now();
    node.stats.recover += n;
}

void incrementRecoverByUri(const std::string& uri, uint64_t n) {
    std::string sid;
    {
        std::lock_guard<std::mutex> lk(g_uri_mutex);
        auto it = g_uri_to_source.find(uri);
        if (it != g_uri_to_source.end()) sid = it->second;
    }
    if (sid.empty()) return;
    Shard& sh = g_shards[shard_of(sid)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    auto& node = ensure_locked(sh, sid);
    node.last_seen_ms = va::core::ms_now();
    node.stats.recover += n;
}

void incrementAwaitIdr(const std::string& source_id, uint64_t n) {
    Shard& sh = g_shards[shard_of(source_id)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    auto& node = ensure_locked(sh, source_id);
    node.last_seen_ms = va::core::ms_now();
    node.stats.await_idr += n;
}

void incrementAwaitIdrByUri(const std::string& uri, uint64_t n) {
    std::string sid;
    {
        std::lock_guard<std::mutex> lk(g_uri_mutex);
        auto it = g_uri_to_source.find(uri);
        if (it != g_uri_to_source.end()) sid = it->second;
    }
    if (sid.empty()) return;
    Shard& sh = g_shards[shard_of(sid)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    auto& node = ensure_locked(sh, sid);
    node.last_seen_ms = va::core::ms_now();
    node.stats.await_idr += n;
}

std::vector<Row> snapshot() {
    std::vector<Row> rows;
    for (size_t i=0;i<kNumShards;++i) {
        Shard& sh = g_shards[i];
        std::lock_guard<std::mutex> lk(sh.mtx);
        rows.reserve(rows.size() + sh.by_source.size());
        const int ttl = g_ttl_seconds.load(std::memory_order_relaxed);
        const double now_ms = va::core::ms_now();
        for (auto it = sh.by_source.begin(); it != sh.by_source.end(); ) {
            bool expired = (ttl > 0) && ((now_ms - it->second.last_seen_ms) > (ttl * 1000.0));
            if (expired) {
                it = sh.by_source.erase(it);
            } else {
                Row r; r.source_id = it->first; r.device_recover = it->second.stats.recover; r.await_idr = it->second.stats.await_idr;
                rows.emplace_back(std::move(r));
                ++it;
            }
        }
    }
    return rows;
}

void setTtlSeconds(int ttl_seconds) {
    g_ttl_seconds.store(ttl_seconds, std::memory_order_relaxed);
}

} // namespace va::core::NvdecEvents
