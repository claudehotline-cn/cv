#include "analyzer/triton_session.hpp"
#include "core/logger.hpp"

namespace va::analyzer {

TritonGrpcModelSession::TritonGrpcModelSession(const Options& opt) : opt_(opt) {}
TritonGrpcModelSession::~TritonGrpcModelSession() = default;

bool TritonGrpcModelSession::loadModel(const std::string&, bool) {
#if defined(USE_TRITON_CLIENT)
    // 最小实现占位：实际 gRPC 连接与 metadata 拉取将在后续阶段完成。
    // 当前返回 true 仅表示配置就绪，run() 仍为占位。
    loaded_ = true;
    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton")
        << "init: url='" << opt_.url << "' model='" << opt_.model_name << "'";
    return true;
#else
    VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton")
        << "Triton client is not enabled at build time (USE_TRITON_CLIENT=OFF)";
    loaded_ = false;
    return false;
#endif
}

bool TritonGrpcModelSession::run(const core::TensorView&, std::vector<core::TensorView>& outputs) {
    outputs.clear();
#if defined(USE_TRITON_CLIENT)
    if (!loaded_) return false;
    // 占位：后续实现 gRPC Infer 请求；当前返回 false 触发回退链不影响稳定性。
    return false;
#else
    return false;
#endif
}

IModelSession::ModelRuntimeInfo TritonGrpcModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info;
    info.provider = "triton-grpc";
    info.gpu_active = false; // T0: Host 内存路径；启用 CUDA SHM 后可置 true
    info.io_binding = false;
    info.device_binding = false;
    info.cpu_fallback = false;
    return info;
}

} // namespace va::analyzer

