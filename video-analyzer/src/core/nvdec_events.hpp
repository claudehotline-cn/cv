#pragma once

#include <cstdint>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

namespace va::core::NvdecEvents {

struct Row { std::string source_id; uint64_t device_recover {0}; };

void mapUriToSourceId(const std::string& uri, const std::string& source_id);
void unmapUri(const std::string& uri);

void incrementRecover(const std::string& source_id, uint64_t n = 1);
void incrementRecoverByUri(const std::string& uri, uint64_t n = 1);

std::vector<Row> snapshot();

} // namespace va::core::NvdecEvents

