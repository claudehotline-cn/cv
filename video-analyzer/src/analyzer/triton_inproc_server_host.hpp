#pragma once

#include <memory>
#include <string>
#include <atomic>

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
    };

    static std::shared_ptr<TritonInprocServerHost> instance(const Options& opt);

#if defined(USE_TRITON_INPROCESS)
    ::TRITONSERVER_Server* server() const { return server_; }
    bool isReady() const { return ready_.load(); }
#else
    void* server() const { return nullptr; }
    bool isReady() const { return false; }
#endif

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
