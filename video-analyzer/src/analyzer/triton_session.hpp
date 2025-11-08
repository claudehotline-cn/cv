#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>
#include <string>
#include <vector>
#include <mutex>

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
        // 当 Triton Server 进程与本进程的 CUDA 设备可见序号映射不一致（例如不同 CUDA_VISIBLE_DEVICES）时，
        // 需要指定服务端的设备序号用于 CUDA SHM 注册；默认 <0 表示沿用本地 device_id。
        int shm_server_device_id{-1};
        // 连续注册失败的阈值；达到后本会话禁用 CUDA SHM，避免每帧反复报错。
        unsigned shm_fail_disable_threshold{3};
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
    std::mutex mu_;
    // 持久化 gRPC 客户端，避免每帧创建失败导致静默回退
    std::unique_ptr<triton::client::InferenceServerGrpcClient> client_;
    // 持久化输出缓冲，保证 run() 返回的 TensorView 生命周期
    std::vector<std::vector<uint8_t>> host_out_bufs_;
    std::vector<std::vector<int64_t>> host_out_shapes_;
    // CUDA SHM（T1）：输入区域占位（当前仅占位与降级日志）
    std::string in_shm_name_ {"va_in"};
    size_t in_shm_bytes_ {0};
    const void* last_shm_ptr_ {nullptr};
    void* shm_dev_buf_ {nullptr};
    size_t shm_capacity_ {0};
    bool shm_registered_ {false};
    // 输入侧 SHM 状态
    unsigned in_register_failures_ {0};
    bool in_shm_disabled_ {false};

    // 输出侧 CUDA SHM（T1）
    std::vector<std::string> out_shm_names_;
    std::vector<void*> out_dev_bufs_;
    std::vector<size_t> out_capacity_;
    std::vector<size_t> out_bytes_; // last bytes
    std::vector<bool> out_registered_;
    unsigned out_register_failures_ {0};
    bool out_shm_disabled_ {false};
#endif
};

} // namespace va::analyzer
