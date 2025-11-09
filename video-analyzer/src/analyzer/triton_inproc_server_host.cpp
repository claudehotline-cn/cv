#include "analyzer/triton_inproc_server_host.hpp"
#include "core/logger.hpp"

#if defined(USE_TRITON_INPROCESS)
#include <triton/core/tritonserver.h>
#include <thread>
#include <chrono>
#endif

namespace va::analyzer {

namespace {
std::weak_ptr<TritonInprocServerHost> g_host;
}

std::shared_ptr<TritonInprocServerHost>
TritonInprocServerHost::instance(const Options& opt) {
    auto locked = g_host.lock();
    if (locked) return locked;
    auto h = std::shared_ptr<TritonInprocServerHost>(new TritonInprocServerHost(opt));
    g_host = h; return h;
}

TritonInprocServerHost::TritonInprocServerHost(const Options& opt) {
    (void)init(opt);
}

bool TritonInprocServerHost::init(const Options& opt) {
#if defined(USE_TRITON_INPROCESS)
    // Debug small prints for S3 env (minimal and safe)
    const char* s3_ep = std::getenv("S3_ENDPOINT");
    const char* aws_ep = std::getenv("AWS_ENDPOINT_URL");
    const char* aws_ep_s3 = std::getenv("AWS_ENDPOINT_URL_S3");
    const char* s3_region = std::getenv("S3_REGION");
    const char* aws_region = std::getenv("AWS_REGION");
    VA_LOG_INFO() << "[inproc.triton] repo='" << opt.repo << "' s3_ep='" << (s3_ep? s3_ep: "<unset>")
                  << "' aws_ep='" << (aws_ep? aws_ep: "<unset>")
                  << "' aws_ep_s3='" << (aws_ep_s3? aws_ep_s3: "<unset>")
                  << "' region='" << (s3_region? s3_region: (aws_region? aws_region: "<unset>")) << "'";
    TRITONSERVER_ServerOptions* options = nullptr;
    if (TRITONSERVER_ServerOptionsNew(&options) != nullptr) {
        VA_LOG_ERROR() << "[inproc.triton] ServerOptionsNew failed";
        return false;
    }
    TRITONSERVER_ServerOptionsSetModelRepositoryPath(options, opt.repo.c_str());
    TRITONSERVER_ServerOptionsSetStrictReadiness(options, true);
    // In in-process embedding, exiting on any server error will bring down the host process.
    // Keep it disabled so that inference/model errors are surfaced to callers instead of aborting.
    TRITONSERVER_ServerOptionsSetExitOnError(options, false);
    TRITONSERVER_ServerOptionsSetStrictModelConfig(options, opt.strict_config);
    if (opt.model_control == "explicit") {
        TRITONSERVER_ServerOptionsSetModelControlMode(options, TRITONSERVER_MODEL_CONTROL_EXPLICIT);
    } else {
        TRITONSERVER_ServerOptionsSetModelControlMode(options, TRITONSERVER_MODEL_CONTROL_NONE);
    }
    // 在部分发行版头文件中未暴露 HTTP/GRPC 端口设置原型，这里默认不显式设置端口（保持关闭或默认值）
    TRITONSERVER_ServerOptionsSetLogVerbose(options, opt.log_verbosity);

    TRITONSERVER_Server* server = nullptr;
    TRITONSERVER_Error* err_new = TRITONSERVER_ServerNew(&server, options);
    TRITONSERVER_ServerOptionsDelete(options);
    if (err_new != nullptr) {
        VA_LOG_ERROR() << "[inproc.triton] ServerNew failed";
        return false;
    }
    server_ = server;

    // Wait ready (best-effort)
    for (int i=0;i<120;i++) {
        bool ready = false;
        TRITONSERVER_ServerIsLive(server_, &ready);
        if (ready) { ready_.store(true); break; }
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }
    return ready_.load();
#else
    (void)opt; return false;
#endif
}

TritonInprocServerHost::~TritonInprocServerHost() {
#if defined(USE_TRITON_INPROCESS)
    if (server_) {
        TRITONSERVER_ServerDelete(server_);
        server_ = nullptr; ready_.store(false);
    }
#endif
}

} // namespace va::analyzer
