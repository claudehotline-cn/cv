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

struct SessionRow {
    std::int64_t id {0};
    std::string stream_id;
    std::string pipeline;
    std::string model_id;   // nullable
    std::string status;     // Running/Stopped/Failed
    std::string error_msg;  // nullable
    std::int64_t started_ms {0}; // milliseconds since epoch
    std::int64_t stopped_ms {0}; // 0 if NULL
};

struct SourceRow {
    std::string id;
    std::string uri;
    std::string status;    // Unknown/Running/Stopped
    std::string caps_json; // optional JSON string
    double fps {0.0};
    std::int64_t updated_ms {0};
};

} // namespace va::storage
