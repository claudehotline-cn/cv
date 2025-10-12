#pragma once

namespace va { namespace core { namespace errors {

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

inline ErrorCode from_http_status(int status) {
  switch (status) {
    case 200: return ErrorCode::OK;
    case 400: return ErrorCode::INVALID_ARG;
    case 404: return ErrorCode::NOT_FOUND;
    case 409: return ErrorCode::ALREADY_EXISTS;
    case 503: return ErrorCode::UNAVAILABLE;
    default: return ErrorCode::INTERNAL;
  }
}

} } } // namespace va::core::errors

