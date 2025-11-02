#pragma once
#include <string>

namespace lro {

enum class Status { Pending, Running, Ready, Failed, Cancelled };

inline std::string to_string(Status s) {
    switch (s) {
        case Status::Pending:   return "pending";
        case Status::Running:   return "running";
        case Status::Ready:     return "ready";
        case Status::Failed:    return "failed";
        case Status::Cancelled: return "cancelled";
    }
    return "unknown";
}

} // namespace lro

