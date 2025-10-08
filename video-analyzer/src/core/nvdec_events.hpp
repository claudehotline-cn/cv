#pragma once

#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::core::NvdecEvents {

struct Row {
    std::string source_id;
    uint64_t device_recover {0};
    uint64_t await_idr {0};
};

void mapUriToSourceId(const std::string& uri, const std::string& source_id);
void unmapUri(const std::string& uri);

void incrementRecover(const std::string& source_id, uint64_t n = 1);
void incrementRecoverByUri(const std::string& uri, uint64_t n = 1);

void incrementAwaitIdr(const std::string& source_id, uint64_t n = 1);
void incrementAwaitIdrByUri(const std::string& uri, uint64_t n = 1);

std::vector<Row> snapshot();

// Optional: set TTL (seconds) for idle per-source entries. <=0 disables TTL pruning.
void setTtlSeconds(int ttl_seconds);

} // namespace va::core::NvdecEvents
