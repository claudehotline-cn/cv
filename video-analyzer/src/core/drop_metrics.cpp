#include "core/drop_metrics.hpp"

#include <algorithm>
#include <unordered_map>

namespace va::core::DropMetrics {

namespace {
std::mutex g_uri_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id

struct Shard {
    std::mutex mtx;
    std::unordered_map<std::string, Counters> by_source;
};

constexpr size_t kNumShards = 16;
static Shard g_shards[kNumShards];

static inline size_t shard_of(const std::string& sid) {
    return std::hash<std::string>{}(sid) & (kNumShards - 1);
}

Counters& ensure_locked(Shard& sh, const std::string& sid) {
    auto it = sh.by_source.find(sid);
    if (it == sh.by_source.end()) {
        it = sh.by_source.try_emplace(sid).first;
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

void increment(const std::string& source_id, Reason reason, uint64_t n) {
    Shard& sh = g_shards[shard_of(source_id)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    Counters& c = ensure_locked(sh, source_id);
    switch (reason) {
        case Reason::QueueOverflow: c.queue_overflow.fetch_add(n); break;
        case Reason::DecodeError:   c.decode_error.fetch_add(n); break;
        case Reason::EncodeEagain:  c.encode_eagain.fetch_add(n); break;
        case Reason::Backpressure:  c.backpressure.fetch_add(n); break;
    }
}

void incrementByUri(const std::string& uri, Reason reason, uint64_t n) {
    std::string sid;
    {
        std::lock_guard<std::mutex> lk(g_uri_mutex);
        auto it = g_uri_to_source.find(uri);
        if (it != g_uri_to_source.end()) sid = it->second;
    }
    if (sid.empty()) return;
    Shard& sh = g_shards[shard_of(sid)];
    std::lock_guard<std::mutex> lk(sh.mtx);
    Counters& c = ensure_locked(sh, sid);
    switch (reason) {
        case Reason::QueueOverflow: c.queue_overflow.fetch_add(n); break;
        case Reason::DecodeError:   c.decode_error.fetch_add(n); break;
        case Reason::EncodeEagain:  c.encode_eagain.fetch_add(n); break;
        case Reason::Backpressure:  c.backpressure.fetch_add(n); break;
    }
}

std::vector<SnapshotRow> snapshot() {
    std::vector<SnapshotRow> rows;
    for (size_t i=0;i<kNumShards;++i) {
        Shard& sh = g_shards[i];
        std::lock_guard<std::mutex> lk(sh.mtx);
        rows.reserve(rows.size() + sh.by_source.size());
        for (auto& kv : sh.by_source) {
            SnapshotRow r;
            r.source_id = kv.first;
            r.counters.queue_overflow = kv.second.queue_overflow.load();
            r.counters.decode_error   = kv.second.decode_error.load();
            r.counters.encode_eagain  = kv.second.encode_eagain.load();
            r.counters.backpressure   = kv.second.backpressure.load();
            rows.emplace_back(std::move(r));
        }
    }
    return rows;
}

} // namespace va::core::DropMetrics
