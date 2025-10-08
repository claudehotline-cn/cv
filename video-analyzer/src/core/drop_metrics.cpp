#include "core/drop_metrics.hpp"

#include <algorithm>
#include <unordered_map>

namespace va::core::DropMetrics {

namespace {
std::mutex g_mutex;
std::unordered_map<std::string, std::string> g_uri_to_source; // uri -> source_id
std::unordered_map<std::string, Counters> g_by_source;        // source_id -> counters

Counters& ensure(const std::string& sid) {
    auto it = g_by_source.find(sid);
    if (it == g_by_source.end()) {
        auto res = g_by_source.try_emplace(sid);
        it = res.first;
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

void increment(const std::string& source_id, Reason reason, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    Counters& c = ensure(source_id);
    switch (reason) {
        case Reason::QueueOverflow: c.queue_overflow.fetch_add(n); break;
        case Reason::DecodeError:   c.decode_error.fetch_add(n); break;
        case Reason::EncodeEagain:  c.encode_eagain.fetch_add(n); break;
        case Reason::Backpressure:  c.backpressure.fetch_add(n); break;
    }
}

void incrementByUri(const std::string& uri, Reason reason, uint64_t n) {
    std::lock_guard<std::mutex> lk(g_mutex);
    auto it = g_uri_to_source.find(uri);
    if (it != g_uri_to_source.end()) {
        Counters& c = ensure(it->second);
        switch (reason) {
            case Reason::QueueOverflow: c.queue_overflow.fetch_add(n); break;
            case Reason::DecodeError:   c.decode_error.fetch_add(n); break;
            case Reason::EncodeEagain:  c.encode_eagain.fetch_add(n); break;
            case Reason::Backpressure:  c.backpressure.fetch_add(n); break;
        }
    }
}

std::vector<SnapshotRow> snapshot() {
    std::lock_guard<std::mutex> lk(g_mutex);
    std::vector<SnapshotRow> rows;
    rows.reserve(g_by_source.size());
    for (auto& kv : g_by_source) {
        SnapshotRow r;
        r.source_id = kv.first;
        r.counters.queue_overflow = kv.second.queue_overflow.load();
        r.counters.decode_error   = kv.second.decode_error.load();
        r.counters.encode_eagain  = kv.second.encode_eagain.load();
        r.counters.backpressure   = kv.second.backpressure.load();
        rows.emplace_back(std::move(r));
    }
    return rows;
}

} // namespace va::core::DropMetrics
