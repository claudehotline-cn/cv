#pragma once

#include <atomic>
#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::core::SourceReconnects {

struct Row { std::string source_id; uint64_t reconnects {0}; };

void mapUriToSourceId(const std::string& uri, const std::string& source_id);
void unmapUri(const std::string& uri);

void increment(const std::string& source_id, uint64_t n = 1);
void incrementByUri(const std::string& uri, uint64_t n = 1);

std::vector<Row> snapshot();

} // namespace va::core::SourceReconnects

