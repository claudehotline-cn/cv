// Minimal DB record definitions used by repositories (skeleton)
#pragma once

#include <cstdint>
#include <string>

namespace va::storage {

struct EventRow {
    // milliseconds since epoch; mapped to DATETIME by application/sql layer
    std::int64_t ts_ms {0};
    std::string level;     // info/warn/error
    std::string type;      // same as level or custom
    std::string pipeline;  // nullable
    std::string node;      // nullable
    std::string stream_id; // nullable
    std::string msg;
    std::string extra_json; // optional JSON string
};

struct LogRow {
    std::int64_t ts_ms {0};
    std::string level;     // info/warn/error
    std::string pipeline;  // nullable
    std::string node;      // nullable
    std::string stream_id; // nullable
    std::string message;
    std::string extra_json; // optional JSON string
};

} // namespace va::storage

