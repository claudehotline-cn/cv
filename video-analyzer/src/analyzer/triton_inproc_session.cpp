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

    // 当未显式配置 input_name 时，尝试通过 Triton metadata 自动填充第一个输入名，
    // 以避免对全局 triton_input=images 的硬编码依赖。
    if (opt_.input_name.empty()) {
        auto* server = host_->server();
        if (server) {
            TRITONSERVER_Message* md = nullptr;
            TRITONSERVER_Error* e_md = TRITONSERVER_ServerModelMetadata(
                server,
                opt_.model_name.c_str(),
                (opt_.model_version.empty() ? -1 : std::strtoll(opt_.model_version.c_str(), nullptr, 10)),
                &md);
            if (e_md != nullptr) {
                VA_LOG_WARN() << "[inproc.triton] ModelMetadata failed for model '" << opt_.model_name
                              << "': " << TRITONSERVER_ErrorMessage(e_md);
                TRITONSERVER_ErrorDelete(e_md);
            } else if (md) {
                const char* buf = nullptr;
                size_t size = 0;
                TRITONSERVER_Error* e_js = TRITONSERVER_MessageSerializeToJson(md, &buf, &size);
                if (e_js != nullptr) {
                    VA_LOG_WARN() << "[inproc.triton] MessageSerializeToJson failed for model '" << opt_.model_name
                                  << "': " << TRITONSERVER_ErrorMessage(e_js);
                    TRITONSERVER_ErrorDelete(e_js);
                } else if (buf && size > 0) {
                    try {
                        std::string json(buf, size);
                        std::string in_name;
                        auto pos_inputs = json.find("\"inputs\"");
                        if (pos_inputs != std::string::npos) {
                            auto pos_name = json.find("\"name\"", pos_inputs);
                            if (pos_name != std::string::npos) {
                                auto pos_colon = json.find(':', pos_name);
                                auto pos_q1 = json.find('"', pos_colon);
                                auto pos_q2 = (pos_q1 == std::string::npos) ? std::string::npos
                                                                             : json.find('"', pos_q1 + 1);
                                if (pos_q1 != std::string::npos && pos_q2 != std::string::npos && pos_q2 > pos_q1 + 1) {
                                    in_name = json.substr(pos_q1 + 1, pos_q2 - pos_q1 - 1);
                                }
                            }
                        }
                        if (!in_name.empty()) {
                            opt_.input_name = in_name;
                            VA_LOG_INFO() << "[inproc.triton] autofill input_name='" << opt_.input_name
                                          << "' for model='" << opt_.model_name << "'";
                        }
                    } catch (...) {
                        // best-effort: 若解析失败则保持 input_name 为空，由后续错误日志协助诊断
                    }
                }
                TRITONSERVER_MessageDelete(md);
            }
        }
    }
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
    // DebugSeg：入口打点，记录输入 tensor 形状与 GPU 标志，便于精确定位崩溃前状态
    try {
        std::string shape_str;
        for (size_t i = 0; i < input.shape.size(); ++i) {
            if (i) shape_str += "x";
            shape_str += std::to_string(input.shape[i]);
        }
        VA_LOG_C(::va::core::LogLevel::Info, "inproc.triton")
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
        for (int i=0;i<n;i++) { std::vector<va::core::TensorView> toss; (void)this->run(input, toss); }
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
    if (input.on_gpu && opt_.use_gpu_input) {
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
        const char* msg = err_req ? TRITONSERVER_ErrorMessage(err_req) : "null request";
        VA_LOG_WARN() << "[inproc.triton] InferenceRequestNew failed: " << msg;
        if (err_req) TRITONSERVER_ErrorDelete(err_req);
        return false;
    }
    TRITONSERVER_InferenceRequestSetId(req, "va-inproc");
    TRITONSERVER_InferenceRequestSetTimeoutMicroseconds(req, static_cast<uint64_t>(opt_.timeout_ms) * 1000ull);
    // Ensure server owns request lifetime once enqueued; we won't call Delete after InferAsync
    auto req_release = [](TRITONSERVER_InferenceRequest* /*request*/, unsigned int /*release_flags*/, void* /*userp*/) {
        // no-op: buffers are managed by this session and remain valid until run() completes
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
        VA_LOG_C(::va::core::LogLevel::Info, "inproc.triton")
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
	
	    // 使用默认 ResponseAllocator，通过 InferenceResponseOutput 获取输出 buffer；
	    // 对 GPU 输出再做一次 D2D 拷贝到会话持久化的 GPU 缓冲，避免 Triton 在自定义 allocator 路径上的崩溃。
	    // Sync via promise
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
	            nullptr,
	            nullptr,
	            resp_cb,
	            &prom); e != nullptr) {
	        VA_LOG_WARN() << "[inproc.triton] SetResponseCallback failed: " << TRITONSERVER_ErrorMessage(e);
	        TRITONSERVER_ErrorDelete(e);
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
	        VA_LOG_C(::va::core::LogLevel::Info, "inproc.triton")
	            << "[DebugSeg] ServerInferAsync dispatched model='" << opt_.model_name
	            << "' use_gpu_output=" << std::boolalpha << opt_.use_gpu_output;
	    } catch (...) {}
	
	    TRITONSERVER_InferenceResponse* resp = fut.get();
	    if (!resp) {
	        VA_LOG_WARN() << "[inproc.triton] null response";
	        return false;
	    }
	
	    // Check response error explicitly to avoid undefined behavior and hard crashes
	    if (auto* rerr = TRITONSERVER_InferenceResponseError(resp); rerr != nullptr) {
	        const char* emsg = TRITONSERVER_ErrorMessage(rerr);
	        VA_LOG_WARN() << "[inproc.triton] response error: " << (emsg ? emsg : "<unknown>");
	        TRITONSERVER_ErrorDelete(rerr);
	        TRITONSERVER_InferenceResponseDelete(resp);
	        return false;
	    }
	
	    // Parse outputs；优先返回 GPU 视图，否则复制到 host_out_bufs_
	    uint32_t outc = 0; 
	    if (auto* e = TRITONSERVER_InferenceResponseOutputCount(resp, &outc); e != nullptr) {
	        VA_LOG_WARN() << "[inproc.triton] OutputCount failed: " << TRITONSERVER_ErrorMessage(e);
	        TRITONSERVER_ErrorDelete(e);
	        TRITONSERVER_InferenceResponseDelete(resp);
	        return false;
	    }
    try {
        VA_LOG_C(::va::core::LogLevel::Info, "inproc.triton")
            << "[DebugSeg] OutputCount=" << outc << " model='" << opt_.model_name << "'";
    } catch (...) {}
    host_out_bufs_.clear(); host_out_shapes_.clear(); outputs.clear();
    // 当 output_names 为空时，收集响应中的真实输出名，供后续请求与 NodeModel 映射使用。
    std::vector<std::string> discovered_names;
    bool need_discover = opt_.output_names.empty();
    for (uint32_t i=0;i<outc;i++) {
        const char* oname = nullptr; TRITONSERVER_DataType odt; const int64_t* odims=nullptr; uint64_t odimc=0;
        const void* base = nullptr; size_t bsize = 0; TRITONSERVER_MemoryType mtype; int64_t mid=0; void* userp=nullptr;
        if (auto* e = TRITONSERVER_InferenceResponseOutput(resp, i, &oname, &odt, &odims, &odimc, &base, &bsize, &mtype, &mid, &userp); e != nullptr) {
            VA_LOG_WARN() << "[inproc.triton] ResponseOutput[" << i << "] failed: " << TRITONSERVER_ErrorMessage(e);
            TRITONSERVER_ErrorDelete(e);
            continue;
        }
        try {
            VA_LOG_C(::va::core::LogLevel::Info, "inproc.triton")
                << "[DebugSeg] ResponseOutput[" << i << "] name='" << (oname ? oname : "<null>")
                << "' bytes=" << bsize
                << " mtype=" << static_cast<int>(mtype)
                << " mid=" << mid;
        } catch (...) {}
        if (need_discover) {
            if (oname && *oname) {
                discovered_names.emplace_back(oname);
            } else {
                discovered_names.emplace_back(std::string("output") + std::to_string(i));
            }
        }
        (void)odt; // 假定为 FP32
        if (!base || bsize == 0) continue;
        std::vector<int64_t> shape(odims, odims + odimc);
        // 若下游期望 batch=1，则可在此补前导维（与 gRPC 版对齐）
        if (!input.shape.empty() && input.shape.size()==4 && input.shape.front()==1 && shape.size()==2) {
            std::vector<int64_t> with_batch; with_batch.reserve(shape.size()+1); with_batch.push_back(1);
            with_batch.insert(with_batch.end(), shape.begin(), shape.end()); shape.swap(with_batch);
        }
        if (mtype == TRITONSERVER_MEMORY_GPU && mid == opt_.device_id && opt_.use_gpu_output) {
            // 设备侧输出：从 Triton 默认分配的 GPU 缓冲 D2D 拷贝到会话持久化的 GPU 缓冲，
            // 确保 ResponseDelete 后 TensorView 仍然有效。
#if defined(USE_CUDA)
            { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
            if (out_capacity_.size() <= i) {
                out_capacity_.resize(i+1, 0);
                out_dev_bufs_.resize(i+1, nullptr);
            }
            size_t alloc_size = next_pow2(bsize);
            if (out_capacity_[i] < alloc_size || out_dev_bufs_[i] == nullptr) {
                if (out_dev_bufs_[i]) cudaFree(out_dev_bufs_[i]);
                if (cudaSuccess != cudaMalloc(&out_dev_bufs_[i], alloc_size)) {
                    out_dev_bufs_[i] = nullptr; out_capacity_[i] = 0;
                } else {
                    out_capacity_[i] = alloc_size;
                }
            }
            if (!out_dev_bufs_[i]) {
                VA_LOG_WARN() << "[inproc.triton] cudaMalloc for output D2D buffer failed, falling back to host";
                // 回退到 CPU 路径
                goto stage_to_host;
            }
            {
                auto cerr = cudaMemcpy(out_dev_bufs_[i], base, bsize, cudaMemcpyDeviceToDevice);
                if (cerr != cudaSuccess) {
                    VA_LOG_WARN() << "[inproc.triton] cudaMemcpy output D2D failed: " << cudaGetErrorString(cerr);
                    continue;
                }
            }
            {
                va::core::TensorView tv;
                tv.on_gpu = true;
                tv.dtype = va::core::DType::F32;
                tv.data = out_dev_bufs_[i];
                tv.shape = shape;
                outputs.push_back(tv);
            }
#else
            VA_LOG_WARN() << "[inproc.triton] output on GPU but CUDA not enabled; skipping";
            continue;
#endif
        } else {
stage_to_host:
            if (mtype == TRITONSERVER_MEMORY_GPU) {
                // Stage device buffer to host when默认分配器返回 GPU 但我们需要 CPU 视图
#if defined(USE_CUDA)
                std::vector<uint8_t> cpu; cpu.resize(bsize);
                auto cerr = cudaMemcpy(cpu.data(), base, bsize, cudaMemcpyDeviceToHost);
                if (cerr != cudaSuccess) {
                    VA_LOG_WARN() << "[inproc.triton] cudaMemcpy output D2H failed: " << cudaGetErrorString(cerr);
                    continue;
                }
                host_out_bufs_.emplace_back(std::move(cpu));
                host_out_shapes_.push_back(shape);
                va::core::TensorView tv; tv.on_gpu=false; tv.dtype=va::core::DType::F32; tv.data=host_out_bufs_.back().data(); tv.shape=host_out_shapes_.back(); outputs.push_back(tv);
#else
                VA_LOG_WARN() << "[inproc.triton] output on GPU but CUDA not enabled; skipping";
                continue;
#endif
            } else {
                host_out_bufs_.emplace_back(reinterpret_cast<const uint8_t*>(base), reinterpret_cast<const uint8_t*>(base) + bsize);
                host_out_shapes_.push_back(shape);
                va::core::TensorView tv; tv.on_gpu=false; tv.dtype=va::core::DType::F32; tv.data=host_out_bufs_.back().data(); tv.shape=host_out_shapes_.back(); outputs.push_back(tv);
            }
        }
    }
    // 若本会话之前未显式配置输出名且本次推理成功获取到输出，
    // 则将名称持久化到 opt_ 中，供后续 AddRequestedOutput 以及 NodeModel::process 使用。
	    if (need_discover && !discovered_names.empty()) {
	        opt_.output_names = std::move(discovered_names);
	        VA_LOG_INFO() << "[inproc.triton] autofill output_names (n=" << opt_.output_names.size()
	                      << ") for model='" << opt_.model_name << "'";
	    }
	    TRITONSERVER_InferenceResponseDelete(resp);
	    return !outputs.empty();
#else
    (void)input; (void)outputs; return false;
#endif
}

IModelSession::ModelRuntimeInfo TritonInprocModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info; info.provider = "triton-inproc"; info.gpu_active=false; info.io_binding=false; info.device_binding=false; info.cpu_fallback=false; return info;
}

} // namespace va::analyzer
