#pragma once

#include <memory>
#include <string>

namespace va { namespace control {

class PipelineController; // fwd

// 在未启用 gRPC 的情况下，提供空壳类型与启动函数，避免链接依赖
class AnalyzerControlService { };

struct OpaquePtr; // from interfaces

OpaquePtr StartGrpcServer(const std::string& /*addr*/, AnalyzerControlService* /*svc*/);

// 便捷封装：根据控制器与地址启动（未启用 gRPC 时返回空）
OpaquePtr StartGrpcServer(const std::string& addr, PipelineController* ctl);

} } // namespace
