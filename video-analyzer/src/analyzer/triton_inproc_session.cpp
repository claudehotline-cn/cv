#include "analyzer/triton_inproc_session.hpp"
#include "analyzer/triton_inproc_server_host.hpp"
#include "core/logger.hpp"
#include "analyzer/logging_util.hpp"

#include <atomic>
#include <future>
#include <cstring>

#if defined(USE_TRITON_INPROCESS)
#include <triton/core/tritonserver.h>
#if defined(USE_CUDA)
#include <cuda_runtime.h>
#endif
#endif

namespace {
// 近似 size-class：向上取 2 的幂，降低频繁重分配带来的碎片与抖动
static inline size_t next_pow2(size_t v) {
    if (v == 0) return 0; v--; v |= v >> 1; v |= v >> 2; v |= v >> 4; v |= v >> 8; v |= v >> 16;
#if SIZE_MAX > 0xFFFFFFFFu
    v |= v >> 32;
#endif
    return v + 1;
}
}

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
    hopt.repository_poll_secs = opt_.repository_poll_secs;
    // 透传 ServerOptions 增强项
    hopt.backend_dir = opt_.backend_dir;
    hopt.pinned_mem_pool_mb = opt_.pinned_mem_pool_mb;
    hopt.cuda_pool_device_id = opt_.cuda_pool_device_id;
    hopt.cuda_pool_bytes = opt_.cuda_pool_bytes;
    hopt.backend_configs = opt_.backend_configs;
    auto host = TritonInprocServerHost::instance(hopt);
    if (!host || !host->isReady()) {
        VA_LOG_WARN() << "[inproc.triton] server not ready";
        loaded_ = false; return false;
    }
    // MODE_EXPLICIT: 主动加载；否则依赖模型仓库预加载
    if (opt_.model_control == std::string("explicit")) {
        auto* server = host->server();
        if (!server) { VA_LOG_WARN() << "[inproc.triton] null server"; return false; }
        if (auto* e = TRITONSERVER_ServerLoadModel(server, opt_.model_name.c_str()); e != nullptr) {
            VA_LOG_WARN() << "[inproc.triton] LoadModel('" << opt_.model_name << "') failed: " << TRITONSERVER_ErrorMessage(e);
            TRITONSERVER_ErrorDelete(e);
            loaded_ = false; return false;
        }
    }
    host_ = host;
    // Phase 1：依赖模型仓库已预加载模型（MODE_NONE/auto）
    loaded_ = true;
    VA_LOG_INFO() << "[inproc.triton] init model='" << opt_.model_name << "'";
    // 不再通过 ModelMetadata 动态发现输入名，要求在配置（engine options 或 per-node triton_input）中显式提供。
    if (opt_.input_name.empty()) {
        VA_LOG_ERROR() << "[inproc.triton] input_name is empty for model='"
                       << opt_.model_name << "', repo='" << opt_.repo_path
                       << "'. Please configure triton_input explicitly in engine or graph.";
        loaded_ = false;
        host_.reset();
        return false;
    }
    return true;
#else
    (void)opt_;
    VA_LOG_WARN() << "[inproc.triton] build without USE_TRITON_INPROCESS";
    return false;
#endif
}

bool TritonInprocModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    return run_impl(input, outputs, false);
}

bool TritonInprocModelSession::run_impl(const core::TensorView& input,
                                        std::vector<core::TensorView>& outputs,
                                        bool force_cpu_input) {
    outputs.clear();
#if defined(USE_TRITON_INPROCESS)
    // DebugSeg：入口打点，改用节流日志，避免每帧刷 Info。
    try {
        std::string shape_str;
        for (size_t i = 0; i < input.shape.size(); ++i) {
            if (i) shape_str += "x";
            shape_str += std::to_string(input.shape[i]);
        }
        auto lvl = va::analyzer::logutil::log_level_for_tag("inproc.triton");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("inproc.triton");
        VA_LOG_THROTTLED(lvl, "inproc.triton", thr)
            << "[DebugSeg] TritonInproc::run enter model='" << opt_.model_name
            << "' on_gpu=" << std::boolalpha << input.on_gpu
            << " shape=" << shape_str
            << " use_gpu_input=" << opt_.use_gpu_input
            << " use_gpu_output=" << opt_.use_gpu_output;
    } catch (...) { /* best-effort */ }
    // Lazy warmup based on first real input's shape
    if (!warmed_ && !in_warmup_ && opt_.warmup_runs != 0) {
        int n = (opt_.warmup_runs < 0) ? 1 : opt_.warmup_runs;
        in_warmup_ = true;
        for (int i = 0; i < n; ++i) {
            std::vector<va::core::TensorView> toss;
            (void)this->run_impl(input, toss, force_cpu_input);
        }
        in_warmup_ = false; warmed_ = true;
    }
    if (!host_ || !host_->isReady()) {
        TritonInprocServerHost::Options hopt; 
        hopt.repo = opt_.repo_path;
        hopt.enable_http = opt_.enable_http; hopt.http_port = opt_.http_port;
        hopt.enable_grpc = opt_.enable_grpc; hopt.grpc_port = opt_.grpc_port;
        hopt.strict_config = opt_.strict_config; 
        hopt.model_control = opt_.model_control; // honor session option (e.g., explicit)
        // propagate advanced ServerOptions to keep host consistent
        hopt.backend_dir = opt_.backend_dir;
        hopt.pinned_mem_pool_mb = opt_.pinned_mem_pool_mb;
        hopt.cuda_pool_device_id = opt_.cuda_pool_device_id;
        hopt.cuda_pool_bytes = opt_.cuda_pool_bytes;
        hopt.backend_configs = opt_.backend_configs;
        host_ = TritonInprocServerHost::instance(hopt);
    }
    if (!host_ || !host_->isReady()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "inproc.triton")
            << "[DebugSeg] host_ not ready in run() model='" << opt_.model_name << "'";
        return false;
    }
    auto* server = host_->server();
    if (!server) {
        VA_LOG_C(::va::core::LogLevel::Warn, "inproc.triton")
            << "[DebugSeg] null server in run() model='" << opt_.model_name << "'";
        return false;
    }

    // Prepare input (支持 GPU 直通)
    size_t elem = 1; for (auto d : input.shape) elem *= static_cast<size_t>(d);
    const size_t bytes = elem * sizeof(float);
    std::vector<uint8_t> host_stage;
    const uint8_t* host_ptr = reinterpret_cast<const uint8_t*>(input.data);
    bool use_gpu_input = false;
    if (input.on_gpu && opt_.use_gpu_input && !force_cpu_input) {
#if defined(USE_CUDA)
        use_gpu_input = true;
        // ensure device
        { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
        // Validate that the device pointer matches the configured device
        cudaPointerAttributes attrs{};
        if (cudaSuccess == cudaPointerGetAttributes(&attrs, input.data)) {
#if CUDART_VERSION >= 10000
            int ptr_dev = attrs.device;
#else
            int ptr_dev = attrs.device;
#endif
            if (ptr_dev != opt_.device_id) {
                VA_LOG_WARN() << "[inproc.triton] input device pointer on GPU " << ptr_dev << ", expected GPU " << opt_.device_id;
            }
        }
#else
        VA_LOG_WARN() << "[inproc.triton] input.on_gpu=true but CUDA not enabled";
        return false;
#endif
    } else if (input.on_gpu) {
#if defined(USE_CUDA)
        // CPU staging 路径：优先根据指针属性判断其所属 device，并切换到对应 device 后再执行 D2H。
        cudaPointerAttributes attrs{};
        bool is_dev_ptr = false;
        int dev_for_copy = opt_.device_id;
        if (cudaSuccess == cudaPointerGetAttributes(&attrs, input.data)) {
#if CUDART_VERSION >= 10000
            if (attrs.type == cudaMemoryTypeDevice || attrs.type == cudaMemoryTypeManaged) {
                is_dev_ptr = true;
                dev_for_copy = attrs.device;
            }
#else
            is_dev_ptr = true;
            dev_for_copy = attrs.device;
#endif
        }
        if (!is_dev_ptr) {
            // 指针并非设备内存（例如误标记为 on_gpu），直接当作 host 指针使用，避免错误的 D2H。
            host_ptr = reinterpret_cast<const uint8_t*>(input.data);
        } else {
            int cur_dev = -1;
            (void)cudaGetDevice(&cur_dev);
            if (cur_dev != dev_for_copy) {
                (void)cudaSetDevice(dev_for_copy);
            }
            host_stage.resize(bytes);
            auto err = cudaMemcpy(host_stage.data(), input.data, bytes, cudaMemcpyDeviceToHost);
            if (err != cudaSuccess) {
                VA_LOG_WARN() << "[inproc.triton] cudaMemcpy D2H failed: " << cudaGetErrorString(err);
                return false;
            }
            host_ptr = host_stage.data();
        }
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
        const char* msg = err_req ? TRITONSERVER_ErrorMessage(err_req) : "null request";
        VA_LOG_WARN() << "[inproc.triton] InferenceRequestNew failed: " << msg;
        if (err_req) TRITONSERVER_ErrorDelete(err_req);
        return false;
    }
    TRITONSERVER_InferenceRequestSetId(req, "va-inproc");
    TRITONSERVER_InferenceRequestSetTimeoutMicroseconds(req, static_cast<uint64_t>(opt_.timeout_ms) * 1000ull);
    // In Async 模式下由 Triton 在推理完成后调用 release 回调；在回调中负责删除 request。
    auto req_release = [](TRITONSERVER_InferenceRequest* request, unsigned int /*release_flags*/, void* /*userp*/) {
        if (request) {
            TRITONSERVER_InferenceRequestDelete(request);
        }
    };
    TRITONSERVER_InferenceRequestSetReleaseCallback(req, req_release, nullptr);

    // Input
    TRITONSERVER_DataType dtype = TRITONSERVER_TYPE_FP32;
    if (auto* e = TRITONSERVER_InferenceRequestAddInput(req, opt_.input_name.c_str(), dtype, send_shape.data(), send_shape.size()); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] AddInput failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e);
        TRITONSERVER_InferenceRequestDelete(req);
        return false;
    }
    if (use_gpu_input) {
#if defined(USE_CUDA)
        if (auto* e = TRITONSERVER_InferenceRequestAppendInputData(req, opt_.input_name.c_str(), input.data, bytes, TRITONSERVER_MEMORY_GPU, opt_.device_id); e != nullptr) {
            VA_LOG_WARN() << "[inproc.triton] AppendInputData(GPU) failed: " << TRITONSERVER_ErrorMessage(e);
            TRITONSERVER_ErrorDelete(e);
            TRITONSERVER_InferenceRequestDelete(req);
            return false;
        }
#endif
    } else {
        if (auto* e = TRITONSERVER_InferenceRequestAppendInputData(req, opt_.input_name.c_str(), host_ptr, bytes, TRITONSERVER_MEMORY_CPU, 0 /*id*/); e != nullptr) {
            VA_LOG_WARN() << "[inproc.triton] AppendInputData(CPU) failed: " << TRITONSERVER_ErrorMessage(e);
            TRITONSERVER_ErrorDelete(e);
            TRITONSERVER_InferenceRequestDelete(req);
            return false;
        }
    }

    try {
        auto lvl = va::analyzer::logutil::log_level_for_tag("inproc.triton");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("inproc.triton");
        VA_LOG_THROTTLED(lvl, "inproc.triton", thr)
            << "[DebugSeg] InferenceRequest prepared model='" << opt_.model_name
            << "' input_name='" << opt_.input_name
            << "' use_gpu_input=" << std::boolalpha << use_gpu_input
            << " bytes=" << bytes
            << " output_names=" << opt_.output_names.size();
    } catch (...) {}

    // Outputs：若 output_names 为空，则不显式指定，让 Triton 返回模型配置中的全部输出，
    // 随后在首次推理时自动发现真实输出名并写回 opt_.output_names。
    if (!opt_.output_names.empty()) {
        for (const auto& name : opt_.output_names) {
            if (auto* e = TRITONSERVER_InferenceRequestAddRequestedOutput(req, name.c_str()); e != nullptr) {
                VA_LOG_WARN() << "[inproc.triton] AddRequestedOutput('" << name << "') failed: " << TRITONSERVER_ErrorMessage(e);
                TRITONSERVER_ErrorDelete(e);
                TRITONSERVER_InferenceRequestDelete(req);
                return false;
            }
        }
    }

    // 自定义 ResponseAllocator：优先为已知输出名分配会话持久化的 GPU 缓冲，
    // 未匹配到的输出或禁用 GPU 输出时回退到临时 CPU 缓冲。
    TRITONSERVER_ResponseAllocator* allocator = nullptr;
    struct AllocCtx { TritonInprocModelSession* self; } actx{ this };
    auto alloc_fn = [](TRITONSERVER_ResponseAllocator* /*allocator*/, const char* tensor_name, size_t byte_size,
                       TRITONSERVER_MemoryType preferred_memory_type, int64_t preferred_memory_type_id,
                       void* userp, void** buffer, void** buffer_userp,
                       TRITONSERVER_MemoryType* actual_memory_type, int64_t* actual_memory_type_id) -> TRITONSERVER_Error* {
        (void)preferred_memory_type;
        (void)preferred_memory_type_id;
        auto* ctx = reinterpret_cast<AllocCtx*>(userp);
        auto* self = ctx ? ctx->self : nullptr;
        if (!self || byte_size == 0) {
            *buffer = nullptr;
            *buffer_userp = nullptr;
            *actual_memory_type = TRITONSERVER_MEMORY_CPU;
            *actual_memory_type_id = 0;
            return nullptr;
        }
        // 根据 tensor_name 在配置的输出名列表中查找索引
        size_t idx = 0;
        bool found = false;
        for (size_t i = 0; i < self->opt_.output_names.size(); ++i) {
            if (self->opt_.output_names[i] == tensor_name) {
                idx = i;
                found = true;
                break;
            }
        }
        if (!found) {
            *buffer = nullptr;
            *buffer_userp = nullptr;
            *actual_memory_type = TRITONSERVER_MEMORY_CPU;
            *actual_memory_type_id = 0;
            return nullptr;
        }
#if defined(USE_CUDA)
        if (self->opt_.use_gpu_output) {
            int cur = -1;
            (void)cudaGetDevice(&cur);
            if (cur != self->opt_.device_id) {
                (void)cudaSetDevice(self->opt_.device_id);
            }
            if (self->out_capacity_.size() <= idx) {
                self->out_capacity_.resize(self->opt_.output_names.size(), 0);
                self->out_dev_bufs_.resize(self->opt_.output_names.size(), nullptr);
            }
            if (self->out_capacity_[idx] < byte_size || self->out_dev_bufs_[idx] == nullptr) {
                if (self->out_dev_bufs_[idx]) {
                    cudaFree(self->out_dev_bufs_[idx]);
                    self->out_dev_bufs_[idx] = nullptr;
                    self->out_capacity_[idx] = 0;
                }
                if (cudaSuccess == cudaMalloc(&self->out_dev_bufs_[idx], byte_size)) {
                    self->out_capacity_[idx] = byte_size;
                }
            }
            if (self->out_dev_bufs_[idx]) {
                *buffer = self->out_dev_bufs_[idx];
                *buffer_userp = nullptr; // GPU 缓冲由会话持久化管理，release 不释放
                *actual_memory_type = TRITONSERVER_MEMORY_GPU;
                *actual_memory_type_id = self->opt_.device_id;
                return nullptr;
            }
        }
#endif
        // CPU 回退：为该输出分配一次性 host 缓冲，由 release 回调负责释放
        void* cpu = nullptr;
        if (byte_size) {
            cpu = std::malloc(byte_size);
        }
        *buffer = cpu;
        *buffer_userp = cpu;
        *actual_memory_type = TRITONSERVER_MEMORY_CPU;
        *actual_memory_type_id = 0;
        return nullptr;
    };
    auto release_fn = [](TRITONSERVER_ResponseAllocator* /*allocator*/, void* buffer, void* buffer_userp,
                         size_t /*byte_size*/, TRITONSERVER_MemoryType memory_type, int64_t /*memory_type_id*/) -> TRITONSERVER_Error* {
        // 仅释放我们在 alloc 中通过 malloc 分配的 CPU 缓冲，GPU 缓冲由会话生命周期管理
        if (memory_type == TRITONSERVER_MEMORY_CPU && buffer && buffer_userp == buffer) {
            std::free(buffer);
        }
        return nullptr;
    };
    (void)TRITONSERVER_ResponseAllocatorNew(&allocator, alloc_fn, release_fn, nullptr);

    // Async 推理：使用自定义 ResponseAllocator 获取输出 buffer。
    std::promise<TRITONSERVER_InferenceResponse*> prom;
    auto fut = prom.get_future();
    auto resp_cb = [](TRITONSERVER_InferenceResponse* response, const uint32_t flags, void* userp){
        auto* p = reinterpret_cast<std::promise<TRITONSERVER_InferenceResponse*>*>(userp);
        (void)flags;
        if (p) {
            p->set_value(response);
        }
    };
    if (auto* e = TRITONSERVER_InferenceRequestSetResponseCallback(
            req,
            allocator,
            &actx,
            resp_cb,
            &prom); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] SetResponseCallback failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e);
        if (allocator) {
            TRITONSERVER_ResponseAllocatorDelete(allocator);
        }
        // req 将在 release 回调中由 Triton 删除
        return false;
    }

    TRITONSERVER_Error* err_inf = TRITONSERVER_ServerInferAsync(server, req, nullptr);
    if (err_inf != nullptr) {
        const char* msg = TRITONSERVER_ErrorMessage(err_inf);
        VA_LOG_WARN() << "[inproc.triton] ServerInferAsync failed: " << msg;
        TRITONSERVER_ErrorDelete(err_inf);
        return false;
    }
    try {
        auto lvl = va::analyzer::logutil::log_level_for_tag("inproc.triton");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("inproc.triton");
        VA_LOG_THROTTLED(lvl, "inproc.triton", thr)
            << "[DebugSeg] ServerInferAsync dispatched model='" << opt_.model_name
            << "' use_gpu_output=" << std::boolalpha << opt_.use_gpu_output;
    } catch (...) {}

    TRITONSERVER_InferenceResponse* resp = fut.get();
    if (!resp) {
        VA_LOG_WARN() << "[inproc.triton] null response";
        if (allocator) {
            TRITONSERVER_ResponseAllocatorDelete(allocator);
        }
        return false;
    }

    // Check response error explicitly；若有错误直接返回，避免在错误上下文中继续执行 CUDA 拷贝。
    if (auto* rerr = TRITONSERVER_InferenceResponseError(resp); rerr != nullptr) {
        const char* emsg = TRITONSERVER_ErrorMessage(rerr);
        std::string msg = emsg ? emsg : "";
        TRITONSERVER_ErrorDelete(rerr);
        VA_LOG_WARN() << "[inproc.triton] response error: " << (msg.empty() ? "<unknown>" : msg);
        TRITONSERVER_InferenceResponseDelete(resp);
        if (allocator) {
            TRITONSERVER_ResponseAllocatorDelete(allocator);
        }
        return false;
    }

    // Parse outputs；优先返回 GPU 视图，否则复制到 host_out_bufs_
    uint32_t outc = 0; 
    if (auto* e = TRITONSERVER_InferenceResponseOutputCount(resp, &outc); e != nullptr) {
        VA_LOG_WARN() << "[inproc.triton] OutputCount failed: " << TRITONSERVER_ErrorMessage(e);
        TRITONSERVER_ErrorDelete(e);
        TRITONSERVER_InferenceResponseDelete(resp);
        if (allocator) {
            TRITONSERVER_ResponseAllocatorDelete(allocator);
        }
        return false;
    }
    try {
        auto lvl = va::analyzer::logutil::log_level_for_tag("inproc.triton");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("inproc.triton");
        VA_LOG_THROTTLED(lvl, "inproc.triton", thr)
            << "[DebugSeg] OutputCount=" << outc << " model='" << opt_.model_name << "'";
    } catch (...) {}
    if (opt_.output_names.empty()) {
        VA_LOG_ERROR() << "[inproc.triton] output_names is empty for model='" << opt_.model_name
                       << "'. Please configure triton_outputs explicitly in engine or graph.";
        TRITONSERVER_InferenceResponseDelete(resp);
        if (allocator) {
            TRITONSERVER_ResponseAllocatorDelete(allocator);
        }
        return false;
    }
    host_out_bufs_.clear();
    host_out_shapes_.clear();
    outputs.clear();
    for (uint32_t i=0;i<outc;i++) {
        const char* oname = nullptr; TRITONSERVER_DataType odt; const int64_t* odims=nullptr; uint64_t odimc=0;
        const void* base = nullptr; size_t bsize = 0; TRITONSERVER_MemoryType mtype; int64_t mid=0; void* userp=nullptr;
        if (auto* e = TRITONSERVER_InferenceResponseOutput(resp, i, &oname, &odt, &odims, &odimc, &base, &bsize, &mtype, &mid, &userp); e != nullptr) {
            VA_LOG_WARN() << "[inproc.triton] ResponseOutput[" << i << "] failed: " << TRITONSERVER_ErrorMessage(e);
            TRITONSERVER_ErrorDelete(e);
            continue;
        }
        try {
            auto lvl = va::analyzer::logutil::log_level_for_tag("inproc.triton");
            auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("inproc.triton");
            VA_LOG_THROTTLED(lvl, "inproc.triton", thr)
                << "[DebugSeg] ResponseOutput[" << i << "] name='" << (oname ? oname : "<null>")
                << "' bytes=" << bsize
                << " mtype=" << static_cast<int>(mtype)
                << " mid=" << mid;
        } catch (...) {}
        (void)odt; // 假定为 FP32
        if (!base || bsize == 0) continue;
        std::vector<int64_t> shape(odims, odims + odimc);
        // 若下游期望 batch=1，则可在此补前导维（与 gRPC 版对齐）
        if (!input.shape.empty() && input.shape.size()==4 && input.shape.front()==1 && shape.size()==2) {
            std::vector<int64_t> with_batch; with_batch.reserve(shape.size()+1); with_batch.push_back(1);
            with_batch.insert(with_batch.end(), shape.begin(), shape.end()); shape.swap(with_batch);
        }
        if (mtype == TRITONSERVER_MEMORY_GPU && mid == opt_.device_id && opt_.use_gpu_output) {
            // 设备侧输出（由 ResponseAllocator 提供 GPU 缓冲），直接暴露 device TensorView
            va::core::TensorView tv;
            tv.on_gpu = true;
            tv.dtype = va::core::DType::F32;
            tv.data = const_cast<void*>(base);
            tv.shape = shape;
            outputs.push_back(tv);
        } else {
#if defined(USE_CUDA)
            if (mtype == TRITONSERVER_MEMORY_GPU) {
                // 当 allocator 回退到 GPU 但当前会话希望 CPU 视图时，显式 D2H 搬运
                std::vector<uint8_t> cpu;
                cpu.resize(bsize);
                auto cerr = cudaMemcpy(cpu.data(), base, bsize, cudaMemcpyDeviceToHost);
                if (cerr != cudaSuccess) {
                    VA_LOG_WARN() << "[inproc.triton] cudaMemcpy output D2H failed: " << cudaGetErrorString(cerr);
                    continue;
                }
                host_out_bufs_.emplace_back(std::move(cpu));
                host_out_shapes_.push_back(shape);
                va::core::TensorView tv;
                tv.on_gpu = false;
                tv.dtype = va::core::DType::F32;
                tv.data = host_out_bufs_.back().data();
                tv.shape = host_out_shapes_.back();
                outputs.push_back(tv);
            } else
#endif
            {
                host_out_bufs_.emplace_back(reinterpret_cast<const uint8_t*>(base),
                                            reinterpret_cast<const uint8_t*>(base) + bsize);
                host_out_shapes_.push_back(shape);
                va::core::TensorView tv;
                tv.on_gpu = false;
                tv.dtype = va::core::DType::F32;
                tv.data = host_out_bufs_.back().data();
                tv.shape = host_out_shapes_.back();
                outputs.push_back(tv);
            }
        }
    }
    TRITONSERVER_InferenceResponseDelete(resp);
    if (allocator) {
        TRITONSERVER_ResponseAllocatorDelete(allocator);
    }
    return !outputs.empty();
#else
    (void)input; (void)outputs; return false;
#endif
}

IModelSession::ModelRuntimeInfo TritonInprocModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info; info.provider = "triton-inproc"; info.gpu_active=false; info.io_binding=false; info.device_binding=false; info.cpu_fallback=false; return info;
}

} // namespace va::analyzer
