#pragma once

#include <string>

namespace vsm::errors {

enum class ErrorCode {
  OK = 0,
  INVALID_ARG,
  NOT_FOUND,
  ALREADY_EXISTS,
  UNAVAILABLE,
  INTERNAL
};

inline const char* to_string(ErrorCode c) {
  switch (c) {
    case ErrorCode::OK: return "OK";
    case ErrorCode::INVALID_ARG: return "INVALID_ARG";
    case ErrorCode::NOT_FOUND: return "NOT_FOUND";
    case ErrorCode::ALREADY_EXISTS: return "ALREADY_EXISTS";
    case ErrorCode::UNAVAILABLE: return "UNAVAILABLE";
    default: return "INTERNAL";
  }
}

inline int http_status(ErrorCode c) {
  switch (c) {
    case ErrorCode::OK: return 200;
    case ErrorCode::INVALID_ARG: return 400;
    case ErrorCode::NOT_FOUND: return 404;
    case ErrorCode::ALREADY_EXISTS: return 409;
    case ErrorCode::UNAVAILABLE: return 503;
    default: return 500;
  }
}

inline ErrorCode map_message(const std::string& msg) {
  if (msg.find("missing") != std::string::npos) return ErrorCode::INVALID_ARG;
  if (msg == "not found") return ErrorCode::NOT_FOUND;
  if (msg == "already exists") return ErrorCode::ALREADY_EXISTS;
  if (msg == "reader start failed") return ErrorCode::UNAVAILABLE;
  if (msg == "too many sse connections") return ErrorCode::UNAVAILABLE;
  return ErrorCode::INTERNAL;
}

} // namespace vsm::errors

