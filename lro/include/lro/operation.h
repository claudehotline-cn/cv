#pragma once
#include <atomic>
#include <string>
#include <memory>
#include <chrono>
#include "lro/status.h"

namespace lro {

struct Operation {
    std::string id;
    std::string idempotency_key;
    std::atomic<Status> status{Status::Pending};
    std::atomic<int>    progress{0}; // 0-100
    std::string phase;               // 业务自定义相位文本（可选）
    std::string reason;              // 失败/取消原因（可选）
    std::string spec_json;           // 业务请求体（可选）
    std::string result_json;         // 业务输出（可选）
    std::chrono::system_clock::time_point created_at{std::chrono::system_clock::now()};
    std::chrono::system_clock::time_point finished_at{}; // 终态时间（Ready/Failed/Cancelled）
};

} // namespace lro
