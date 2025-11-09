#include "analyzer/triton_inproc_server_host.hpp"
#include "core/logger.hpp"

#if defined(USE_TRITON_INPROCESS)
#include <triton/core/tritonserver.h>
#include <thread>
#include <chrono>
#include <sstream>
#include <vector>
#include <cstdlib>
#endif

namespace va::analyzer {

namespace {
std::weak_ptr<TritonInprocServerHost> g_host;
}

std::shared_ptr<TritonInprocServerHost>
TritonInprocServerHost::instance(const Options& opt) {
    auto locked = g_host.lock();
    if (locked) {
#if defined(USE_TRITON_INPROCESS)
        if (locked->compatibleWith(opt)) return locked;
#else
        return locked;
#endif
    }
    auto h = std::shared_ptr<TritonInprocServerHost>(new TritonInprocServerHost(opt));
    g_host = h; return h;
}

TritonInprocServerHost::TritonInprocServerHost(const Options& opt) {
    (void)init(opt);
}

bool TritonInprocServerHost::init(const Options& opt) {
#if defined(USE_TRITON_INPROCESS)
    repo_ = opt.repo; model_control_ = opt.model_control;
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
    } else if (opt.model_control == "poll") {
        TRITONSERVER_ServerOptionsSetModelControlMode(options, TRITONSERVER_MODEL_CONTROL_POLL);
    } else {
        TRITONSERVER_ServerOptionsSetModelControlMode(options, TRITONSERVER_MODEL_CONTROL_NONE);
    }
    // 在部分发行版头文件中未暴露 HTTP/GRPC 端口设置原型，这里默认不显式设置端口（保持关闭或默认值）
    TRITONSERVER_ServerOptionsSetLogVerbose(options, opt.log_verbosity);

    // Backend directory
    std::string backend_dir = opt.backend_dir;
    if (backend_dir.empty()) {
        if (const char* p = std::getenv("TRITON_BACKEND_DIR")) backend_dir = p;
    }
    if (!backend_dir.empty()) {
        TRITONSERVER_ServerOptionsSetBackendDirectory(options, backend_dir.c_str());
        VA_LOG_INFO() << "[inproc.triton] backend_dir='" << backend_dir << "'";
    }

    // Memory pools
    size_t pinned_mb = opt.pinned_mem_pool_mb;
    if (pinned_mb == 0) {
        if (const char* p = std::getenv("TRITON_PINNED_MEM_MB")) {
            pinned_mb = static_cast<size_t>(std::strtoull(p, nullptr, 10));
        }
    }
    if (pinned_mb > 0) {
        TRITONSERVER_ServerOptionsSetPinnedMemoryPoolByteSize(options, pinned_mb << 20);
        VA_LOG_INFO() << "[inproc.triton] pinned_mem_pool_mb=" << pinned_mb;
    }

    size_t cuda_pool_bytes = opt.cuda_pool_bytes;
    if (cuda_pool_bytes == 0) {
        if (const char* p = std::getenv("TRITON_CUDA_MEM_POOL_BYTES")) {
            cuda_pool_bytes = static_cast<size_t>(std::strtoull(p, nullptr, 10));
        }
    }
    if (cuda_pool_bytes > 0) {
        TRITONSERVER_ServerOptionsSetCudaMemoryPoolByteSize(options, opt.cuda_pool_device_id, cuda_pool_bytes);
        VA_LOG_INFO() << "[inproc.triton] cuda_pool_bytes(device=" << opt.cuda_pool_device_id << ")=" << cuda_pool_bytes;
    }

    // Backend-configs: vector or env TRITON_BACKEND_CONFIGS with ';' separated entries of 'backend:key=value'
    auto apply_backend_config = [&](const std::string& entry){
        const auto pos1 = entry.find(':'); if (pos1 == std::string::npos) return;
        const auto pos2 = entry.find('=', pos1+1); if (pos2 == std::string::npos) return;
        std::string bname = entry.substr(0, pos1);
        std::string key = entry.substr(pos1+1, pos2-pos1-1);
        std::string val = entry.substr(pos2+1);
        if (bname.empty() || key.empty()) return;
        TRITONSERVER_ServerOptionsSetBackendConfig(options, bname.c_str(), key.c_str(), val.c_str());
        VA_LOG_INFO() << "[inproc.triton] backend-config " << bname << ":" << key << "=" << val;
    };
    for (const auto& e : opt.backend_configs) apply_backend_config(e);
    if (const char* cfgs = std::getenv("TRITON_BACKEND_CONFIGS")) {
        std::string s = cfgs; std::stringstream ss(s); std::string item;
        while (std::getline(ss, item, ';')) { if (!item.empty()) apply_backend_config(item); }
    }

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

bool TritonInprocServerHost::loadModel(const std::string& name) {
#if defined(USE_TRITON_INPROCESS)
    if (!server_) return false;
    if (auto* e = TRITONSERVER_ServerLoadModel(server_, name.c_str()); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] LoadModel('" << name << "') failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e); return false;
    }
    {
        std::lock_guard<std::mutex> lk(mu_); loaded_.insert(name);
    }
    return true;
#else
    (void)name; return false;
#endif
}

bool TritonInprocServerHost::unloadModel(const std::string& name) {
#if defined(USE_TRITON_INPROCESS)
    if (!server_) return false;
    if (auto* e = TRITONSERVER_ServerUnloadModel(server_, name.c_str()); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] UnloadModel('" << name << "') failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e); return false;
    }
    {
        std::lock_guard<std::mutex> lk(mu_); loaded_.erase(name);
    }
    return true;
#else
    (void)name; return false;
#endif
}

bool TritonInprocServerHost::pollRepository() {
#if defined(USE_TRITON_INPROCESS)
    if (!server_) return false;
    if (auto* e = TRITONSERVER_ServerPollModelRepository(server_); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] PollModelRepository failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e); return false;
    }
    return true;
#else
    return false;
#endif
}

std::vector<std::string> TritonInprocServerHost::currentLoadedModels() const {
#if defined(USE_TRITON_INPROCESS)
    std::lock_guard<std::mutex> lk(mu_);
    return std::vector<std::string>(loaded_.begin(), loaded_.end());
#else
    return {};
#endif
}

bool TritonInprocServerHost::compatibleWith(const Options& opt) const {
#if defined(USE_TRITON_INPROCESS)
    // Require same repo and control mode; more nuanced checks can be added later
    if (repo_ != opt.repo) return false;
    if (model_control_ != opt.model_control) return false;
    return true;
#else
    (void)opt; return true;
#endif
}

} // namespace va::analyzer
