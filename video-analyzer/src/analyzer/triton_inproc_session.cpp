#include "analyzer/triton_inproc_session.hpp"
#include "analyzer/triton_inproc_server_host.hpp"
#include "core/logger.hpp"

#include <atomic>
#include <future>
#include <cstring>

#if defined(USE_TRITON_INPROCESS)
#include <triton/core/tritonserver.h>
#if defined(USE_CUDA)
#include <cuda_runtime.h>
#endif
#endif

namespace va::analyzer {

TritonInprocModelSession::TritonInprocModelSession(const Options& opt) : opt_(opt) {}
TritonInprocModelSession::~TritonInprocModelSession() {
#if defined(USE_TRITON_INPROCESS) && defined(USE_CUDA)
    for (void*& p : out_dev_bufs_) { if (p) { cudaFree(p); p = nullptr; } }
    out_capacity_.clear();
#endif
}

bool TritonInprocModelSession::loadModel(const std::string&, bool) {
#if defined(USE_TRITON_INPROCESS)
    TritonInprocServerHost::Options hopt;
    hopt.repo = opt_.repo_path;
    hopt.enable_http = opt_.enable_http; hopt.http_port = opt_.http_port;
    hopt.enable_grpc = opt_.enable_grpc; hopt.grpc_port = opt_.grpc_port;
    hopt.strict_config = opt_.strict_config; hopt.model_control = opt_.model_control;
    auto host = TritonInprocServerHost::instance(hopt);
    if (!host || !host->isReady()) {
        VA_LOG_WARN() << "[inproc.triton] server not ready";
        loaded_ = false; return false;
    }
    // Phase 1：依赖模型仓库已预加载模型（MODE_NONE/auto）
    loaded_ = true;
    VA_LOG_INFO() << "[inproc.triton] init model='" << opt_.model_name << "'";
    return true;
#else
    (void)opt_;
    VA_LOG_WARN() << "[inproc.triton] build without USE_TRITON_INPROCESS";
    return false;
#endif
}

bool TritonInprocModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    outputs.clear();
#if defined(USE_TRITON_INPROCESS)
    TritonInprocServerHost::Options hopt; hopt.repo = opt_.repo_path;
    auto host = TritonInprocServerHost::instance(hopt);
    if (!host || !host->isReady()) return false;
    auto* server = host->server();
    if (!server) return false;

    // Prepare input (支持 GPU 直通)
    size_t elem = 1; for (auto d : input.shape) elem *= static_cast<size_t>(d);
    const size_t bytes = elem * sizeof(float);
    std::vector<uint8_t> host_stage;
    const uint8_t* host_ptr = reinterpret_cast<const uint8_t*>(input.data);
    bool use_gpu_input = false;
    if (input.on_gpu && opt_.use_gpu_input) {
#if defined(USE_CUDA)
        use_gpu_input = true;
        // ensure device
        { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
#else
        VA_LOG_WARN() << "[inproc.triton] input.on_gpu=true but CUDA not enabled";
        return false;
#endif
    } else if (input.on_gpu) {
#if defined(USE_CUDA)
        host_stage.resize(bytes);
        auto err = cudaMemcpy(host_stage.data(), input.data, bytes, cudaMemcpyDeviceToHost);
        if (err != cudaSuccess) { VA_LOG_WARN() << "[inproc.triton] cudaMemcpy D2H failed: " << cudaGetErrorString(err); return false; }
        host_ptr = host_stage.data();
#else
        VA_LOG_WARN() << "[inproc.triton] input.on_gpu=true but CUDA not enabled"; return false;
#endif
    }

    // Shape: remove batch if assume_no_batch
    std::vector<int64_t> send_shape = input.shape;
    if (opt_.assume_no_batch && send_shape.size() == 4 && send_shape.front() == 1) {
        send_shape.erase(send_shape.begin());
    }

    // Build request
    TRITONSERVER_InferenceRequest* req = nullptr;
    const int64_t ver = (opt_.model_version.empty() ? -1 : std::strtoll(opt_.model_version.c_str(), nullptr, 10));
    TRITONSERVER_Error* err_req = TRITONSERVER_InferenceRequestNew(&req, server, opt_.model_name.c_str(), ver);
    if (err_req != nullptr || !req) {
        VA_LOG_WARN() << "[inproc.triton] InferenceRequestNew failed"; return false;
    }
    TRITONSERVER_InferenceRequestSetId(req, "va-inproc");
    TRITONSERVER_InferenceRequestSetTimeoutMicroseconds(req, static_cast<uint64_t>(opt_.timeout_ms) * 1000ull);

    // Input
    TRITONSERVER_DataType dtype = TRITONSERVER_TYPE_FP32;
    TRITONSERVER_InferenceRequestAddInput(req, opt_.input_name.c_str(), dtype, send_shape.data(), send_shape.size());
    if (use_gpu_input) {
#if defined(USE_CUDA)
        TRITONSERVER_InferenceRequestAppendInputData(req, opt_.input_name.c_str(), input.data, bytes, TRITONSERVER_MEMORY_GPU, opt_.device_id);
#endif
    } else {
        TRITONSERVER_InferenceRequestAppendInputData(req, opt_.input_name.c_str(), host_ptr, bytes, TRITONSERVER_MEMORY_CPU, 0 /*id*/);
    }

    // Outputs
    for (const auto& name : opt_.output_names) {
        TRITONSERVER_InferenceRequestAddRequestedOutput(req, name.c_str());
    }

    // 准备输出分配器（可将输出直接放在 GPU）
    TRITONSERVER_ResponseAllocator* allocator = nullptr;
    struct AllocCtx { TritonInprocModelSession* self; } actx{ this };
    auto alloc_fn = [](TRITONSERVER_ResponseAllocator* /*allocator*/, const char* tensor_name, size_t byte_size,
                       TRITONSERVER_MemoryType preferred_memory_type, int64_t preferred_memory_type_id,
                       void* userp, void** buffer, void** buffer_userp,
                       TRITONSERVER_MemoryType* actual_memory_type, int64_t* actual_memory_type_id) -> TRITONSERVER_Error* {
        (void)preferred_memory_type; (void)preferred_memory_type_id;
        auto* ctx = reinterpret_cast<AllocCtx*>(userp);
        auto* self = ctx->self;
        if (!self || byte_size == 0) { *buffer=nullptr; *buffer_userp=nullptr; *actual_memory_type=TRITONSERVER_MEMORY_CPU; *actual_memory_type_id=0; return nullptr; }
        // 找到输出索引
        size_t idx = 0; bool found=false;
        for (size_t i=0;i<self->opt_.output_names.size();++i) { if (self->opt_.output_names[i] == tensor_name) { idx=i; found=true; break; } }
        if (!found) { *buffer=nullptr; *buffer_userp=nullptr; *actual_memory_type=TRITONSERVER_MEMORY_CPU; *actual_memory_type_id=0; return nullptr; }
#if defined(USE_CUDA)
        if (self->opt_.use_gpu_output) {
            { int cur=-1; (void)cudaGetDevice(&cur); if (cur != self->opt_.device_id) (void)cudaSetDevice(self->opt_.device_id); }
            if (self->out_capacity_.size() <= idx) { self->out_capacity_.resize(self->opt_.output_names.size(), 0); self->out_dev_bufs_.resize(self->opt_.output_names.size(), nullptr); }
            if (self->out_capacity_[idx] < byte_size || self->out_dev_bufs_[idx] == nullptr) {
                if (self->out_dev_bufs_[idx]) cudaFree(self->out_dev_bufs_[idx]);
                if (cudaSuccess != cudaMalloc(&self->out_dev_bufs_[idx], byte_size)) {
                    self->out_dev_bufs_[idx] = nullptr; self->out_capacity_[idx] = 0;
                } else {
                    self->out_capacity_[idx] = byte_size;
                }
            }
            if (self->out_dev_bufs_[idx]) {
                *buffer = self->out_dev_bufs_[idx];
                *buffer_userp = nullptr; // 由会话持久化管理，不在 release 中释放
                *actual_memory_type = TRITONSERVER_MEMORY_GPU;
                *actual_memory_type_id = self->opt_.device_id;
                return nullptr;
            }
        }
#endif
        // CPU 回退
        void* cpu = nullptr; if (byte_size) cpu = std::malloc(byte_size);
        *buffer = cpu; *buffer_userp = cpu;
        *actual_memory_type = TRITONSERVER_MEMORY_CPU; *actual_memory_type_id = 0;
        return nullptr;
    };
    auto release_fn = [](TRITONSERVER_ResponseAllocator* /*allocator*/, void* buffer, void* buffer_userp,
                         size_t /*byte_size*/, TRITONSERVER_MemoryType memory_type, int64_t /*memory_type_id*/) -> TRITONSERVER_Error* {
        // 仅当我们在 alloc 中使用了临时 CPU malloc 时释放；GPU 内存由会话持久化复用
        if (memory_type == TRITONSERVER_MEMORY_CPU && buffer_userp == buffer && buffer) std::free(buffer);
        return nullptr;
    };
    (void)TRITONSERVER_ResponseAllocatorNew(&allocator, alloc_fn, release_fn, nullptr);

    // Sync via promise
    std::promise<TRITONSERVER_InferenceResponse*> prom;
    auto fut = prom.get_future();
    auto resp_cb = [](TRITONSERVER_InferenceResponse* response, const uint32_t flags, void* userp){
        auto* p = reinterpret_cast<std::promise<TRITONSERVER_InferenceResponse*>*>(userp);
        (void)flags; p->set_value(response);
    };
    // 设置响应回调与分配器
    TRITONSERVER_InferenceRequestSetResponseCallback(req, allocator, &actx, resp_cb, &prom);

    TRITONSERVER_Error* err_inf = TRITONSERVER_ServerInferAsync(server, req, nullptr);
    if (err_inf != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] ServerInferAsync failed"; return false;
    }

    TRITONSERVER_InferenceResponse* resp = fut.get();
    if (!resp) { VA_LOG_WARN() << "[inproc.triton] null response"; return false; }

    // Parse outputs；优先返回 GPU 视图（若由分配器给出 GPU 指针），否则复制到 host_out_bufs_
    uint32_t outc = 0; TRITONSERVER_InferenceResponseOutputCount(resp, &outc);
    host_out_bufs_.clear(); host_out_shapes_.clear(); outputs.clear();
    for (uint32_t i=0;i<outc;i++) {
        const char* oname = nullptr; TRITONSERVER_DataType odt; const int64_t* odims=nullptr; uint64_t odimc=0;
        const void* base = nullptr; size_t bsize = 0; TRITONSERVER_MemoryType mtype; int64_t mid=0; void* userp=nullptr;
        TRITONSERVER_InferenceResponseOutput(resp, i, &oname, &odt, &odims, &odimc, &base, &bsize, &mtype, &mid, &userp);
        (void)oname; (void)odt; // 假定为 FP32
        if (!base || bsize == 0) continue;
        std::vector<int64_t> shape(odims, odims + odimc);
        // 若下游期望 batch=1，则可在此补前导维（与 gRPC 版对齐）
        if (!input.shape.empty() && input.shape.size()==4 && input.shape.front()==1 && shape.size()==2) {
            std::vector<int64_t> with_batch; with_batch.reserve(shape.size()+1); with_batch.push_back(1);
            with_batch.insert(with_batch.end(), shape.begin(), shape.end()); shape.swap(with_batch);
        }
        if (mtype == TRITONSERVER_MEMORY_GPU && mid == opt_.device_id && opt_.use_gpu_output) {
            // 设备侧输出（由会话持久化），直接暴露 device TensorView
            va::core::TensorView tv; tv.on_gpu=true; tv.dtype=va::core::DType::F32; tv.data=const_cast<void*>(base); tv.shape=shape; outputs.push_back(tv);
        } else {
            host_out_bufs_.emplace_back(reinterpret_cast<const uint8_t*>(base), reinterpret_cast<const uint8_t*>(base) + bsize);
            host_out_shapes_.push_back(shape);
            va::core::TensorView tv; tv.on_gpu=false; tv.dtype=va::core::DType::F32; tv.data=host_out_bufs_.back().data(); tv.shape=host_out_shapes_.back(); outputs.push_back(tv);
        }
    }
    TRITONSERVER_InferenceResponseDelete(resp);
    if (allocator) TRITONSERVER_ResponseAllocatorDelete(allocator);
    return !outputs.empty();
#else
    (void)input; (void)outputs; return false;
#endif
}

IModelSession::ModelRuntimeInfo TritonInprocModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info; info.provider = "triton-inproc"; info.gpu_active=false; info.io_binding=false; info.device_binding=false; info.cpu_fallback=false; return info;
}

} // namespace va::analyzer
