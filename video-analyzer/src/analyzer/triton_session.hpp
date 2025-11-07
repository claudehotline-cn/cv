#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>
#include <string>
#include <vector>

#if defined(USE_TRITON_CLIENT)
// 前置声明，避免在头文件包含 grpc_client.h 造成全局依赖扩散
namespace triton { namespace client { class InferenceServerGrpcClient; } }
#endif

namespace va::analyzer {

class TritonGrpcModelSession : public IModelSession {
public:
    struct Options {
        std::string url{"localhost:8001"};
        std::string model_name;
        std::string model_version; // empty=latest
        std::string input_name{"images"};
        std::vector<std::string> output_names{"dets"};
        int timeout_ms{2000};
        bool use_cuda_shm{false};
        size_t cuda_shm_bytes{0};
        int device_id{0};
        // Heuristic: treat model as batched (keep NCHW) unless explicitly told otherwise
        bool assume_no_batch{false};
    };

    explicit TritonGrpcModelSession(const Options& opt);
    ~TritonGrpcModelSession() override;

    bool loadModel(const std::string& /*unused*/, bool /*use_gpu*/) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;
    ModelRuntimeInfo getRuntimeInfo() const override;
    std::vector<std::string> outputNames() const override { return opt_.output_names; }

private:
    Options opt_;
    bool loaded_{false};
#if defined(USE_TRITON_CLIENT)
    // 持久化 gRPC 客户端，避免每帧创建失败导致静默回退
    std::unique_ptr<triton::client::InferenceServerGrpcClient> client_;
    // 持久化输出缓冲，保证 run() 返回的 TensorView 生命周期
    std::vector<std::vector<uint8_t>> host_out_bufs_;
    std::vector<std::vector<int64_t>> host_out_shapes_;
#endif
};

} // namespace va::analyzer
