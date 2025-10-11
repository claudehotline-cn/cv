#pragma once

#include "core/logger.hpp"
#include <string>
#include <algorithm>
#include <cstdlib>

namespace va { namespace analyzer { namespace logutil {

inline va::core::LogLevel parse_level(const std::string& s, va::core::LogLevel defv) {
    std::string v = s; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
    if (v=="trace") return va::core::LogLevel::Trace;
    if (v=="debug") return va::core::LogLevel::Debug;
    if (v=="info")  return va::core::LogLevel::Info;
    if (v=="warn"||v=="warning")  return va::core::LogLevel::Warn;
    if (v=="error"||v=="err") return va::core::LogLevel::Error;
    return defv;
}

inline va::core::LogLevel log_level_for_tag(const char* tag, va::core::LogLevel defv = va::core::LogLevel::Debug) {
    // Specific overrides
    if (tag && std::string(tag).find("overlay") != std::string::npos) {
        if (const char* v = std::getenv("VA_OVERLAY_LOG_LEVEL")) return parse_level(v, defv);
    }
    if (tag && std::string(tag).find("yolo") != std::string::npos) {
        if (const char* v = std::getenv("VA_YOLO_LOG_LEVEL")) return parse_level(v, defv);
    }
    if (tag && std::string(tag).rfind("ms.", 0) == 0) { // starts with ms.
        if (const char* v = std::getenv("VA_MS_LOG_LEVEL")) return parse_level(v, defv);
    }
    // Generic override
    if (const char* v = std::getenv("VA_LOG_THROTTLED_LEVEL")) return parse_level(v, defv);
    return defv;
}

inline int parse_int(const char* s, int defv) {
    if (!s) return defv;
    try { return std::max(0, std::stoi(s)); } catch (...) { return defv; }
}

inline int log_throttle_ms_for_tag(const char* tag, int defv = 2000) {
    // Specific overrides first
    if (tag && std::string(tag).find("overlay") != std::string::npos) {
        if (const char* v = std::getenv("VA_OVERLAY_LOG_THROTTLE_MS")) return parse_int(v, defv);
    }
    if (tag && std::string(tag).find("yolo") != std::string::npos) {
        if (const char* v = std::getenv("VA_YOLO_LOG_THROTTLE_MS")) return parse_int(v, defv);
    }
    if (tag && std::string(tag).rfind("ms.", 0) == 0) { // starts with ms.
        if (const char* v = std::getenv("VA_MS_LOG_THROTTLE_MS")) return parse_int(v, defv);
    }
    // Generic fallback
    if (const char* v = std::getenv("VA_LOG_THROTTLE_MS")) return parse_int(v, defv);
    return defv;
}

} } } // namespace va::analyzer::logutil

