#pragma once

#include "analyzer/interfaces.hpp"
#include <memory>
#include <string>
#include <vector>

namespace va::analyzer {

class TritonInprocServerHost; // fwd

// 仅当构建开启 USE_TRITON_INPROCESS 时实现；否则工厂不会选择本实现
class TritonInprocModelSession : public IModelSession {
public:
    struct Options {
        std::string model_name;
        std::string model_version; // empty = latest
        std::string input_name{"images"};
        std::vector<std::string> output_names{"output0"};
        int timeout_ms{2000};
        int device_id{0};
        bool assume_no_batch{false};
        int warmup_runs{0};
        // GPU I/O（in‑process 下无需 CUDA IPC/SHM，可直接传递设备指针与自定义分配器）
        bool use_gpu_input{true};
        bool use_gpu_output{true};
        // Server host options
        std::string repo_path{"/models"};
        bool enable_http{false};
        int http_port{8000};
        bool enable_grpc{false};
        int grpc_port{8001};
        bool strict_config{false};
        std::string model_control{"none"};
        int repository_poll_secs{0};
        // ServerOptions 补充（可从配置或环境注入）
        std::string backend_dir{};
        size_t pinned_mem_pool_mb{0};
        int cuda_pool_device_id{0};
        size_t cuda_pool_bytes{0};
        std::vector<std::string> backend_configs; // 形如 "tensorrt:coalesce_request_input=1"
    };

    explicit TritonInprocModelSession(const Options& opt);
    ~TritonInprocModelSession() override;

    bool loadModel(const std::string& /*unused*/, bool /*use_gpu*/) override;
    bool run(const core::TensorView& input, std::vector<core::TensorView>& outputs) override;
    ModelRuntimeInfo getRuntimeInfo() const override;
    std::vector<std::string> outputNames() const override { return opt_.output_names; }

private:
    Options opt_;
    bool loaded_{false};
    bool warmed_{false};
    bool in_warmup_{false};
    std::shared_ptr<TritonInprocServerHost> host_;
    // host-side output buffers to keep lifetime
    std::vector<std::vector<uint8_t>> host_out_bufs_;
    std::vector<std::vector<int64_t>> host_out_shapes_;
    // device-side persistent output buffers（每个输出一块，可复用）
    std::vector<void*> out_dev_bufs_;
    std::vector<size_t> out_capacity_;
};

} // namespace va::analyzer
