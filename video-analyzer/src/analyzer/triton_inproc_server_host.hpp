#pragma once

#include <memory>
#include <string>
#include <atomic>
#include <vector>

namespace va { namespace core { class Logger; } }

#if defined(USE_TRITON_INPROCESS)
// 在全局命名空间前置声明，与 tritonserver.h 定义保持一致
struct TRITONSERVER_Server;
#endif

namespace va::analyzer {

// 单一职责：仅管理 In‑Process Triton Server 的生命周期与全局配置
class TritonInprocServerHost {
public:
    struct Options {
        std::string repo{ "/models" };
        bool strict_config{false};
        std::string model_control{ "none" }; // none / explicit
        bool enable_http{false};
        int http_port{8000};
        bool enable_grpc{false};
        int grpc_port{8001};
        int log_verbosity{0};
        // 补齐后端目录/内存池/后端配置（等价 --backend-config）
        std::string backend_dir{};              // 可置空：优先使用环境变量 TRITON_BACKEND_DIR
        size_t pinned_mem_pool_mb{0};          // 0 表示不覆盖；也可用 TRITON_PINNED_MEM_MB
        int cuda_pool_device_id{0};            // 设备号（通常与 VA device 对齐）
        size_t cuda_pool_bytes{0};             // 0 表示不覆盖；也可用 TRITON_CUDA_MEM_POOL_BYTES
        // 形如 "tensorrt:coalesce_request_input=1" 的条目，或用环境变量 TRITON_BACKEND_CONFIGS（分号分隔）
        std::vector<std::string> backend_configs;
    };

    static std::shared_ptr<TritonInprocServerHost> instance(const Options& opt);

#if defined(USE_TRITON_INPROCESS)
    ::TRITONSERVER_Server* server() const { return server_; }
    bool isReady() const { return ready_.load(); }
#else
    void* server() const { return nullptr; }
    bool isReady() const { return false; }
#endif

    // Model repository control (best-effort wrappers)
    bool loadModel(const std::string& name);
    bool unloadModel(const std::string& name);
    bool pollRepository();

    ~TritonInprocServerHost();

private:
    explicit TritonInprocServerHost(const Options& opt);
    bool init(const Options& opt);

private:
#if defined(USE_TRITON_INPROCESS)
    ::TRITONSERVER_Server* server_{nullptr};
    std::atomic<bool> ready_{false};
#endif
};

} // namespace va::analyzer
