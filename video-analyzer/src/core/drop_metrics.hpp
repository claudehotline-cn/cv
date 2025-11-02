#pragma once

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::core::DropMetrics {

enum class Reason {
    QueueOverflow,
    DecodeError,
    EncodeEagain,
    Backpressure
};

inline const char* reason_to_cstr(Reason r) {
    switch (r) {
        case Reason::QueueOverflow: return "queue_overflow";
        case Reason::DecodeError:   return "decode_error";
        case Reason::EncodeEagain:  return "encode_eagain";
        case Reason::Backpressure:  return "backpressure";
    }
    return "unknown";
}

struct Counters {
    std::atomic<uint64_t> queue_overflow {0};
    std::atomic<uint64_t> decode_error {0};
    std::atomic<uint64_t> encode_eagain {0};
    std::atomic<uint64_t> backpressure {0};
};

// Register mapping from a source URI to a logical source_id for metrics attribution.
void mapUriToSourceId(const std::string& uri, const std::string& source_id);
// Remove mapping when source is torn down or switched.
void unmapUri(const std::string& uri);

// Increment by explicit source_id.
void increment(const std::string& source_id, Reason reason, uint64_t n = 1);
// Increment by source uri (resolve to source_id if known).
void incrementByUri(const std::string& uri, Reason reason, uint64_t n = 1);

struct PlainCounters {
    uint64_t queue_overflow {0};
    uint64_t decode_error {0};
    uint64_t encode_eagain {0};
    uint64_t backpressure {0};
};

struct SnapshotRow {
    std::string source_id;
    PlainCounters counters;
};

std::vector<SnapshotRow> snapshot();

// Optional: set TTL (seconds) for idle per-source entries. <=0 disables TTL pruning.
void setTtlSeconds(int ttl_seconds);

} // namespace va::core::DropMetrics
