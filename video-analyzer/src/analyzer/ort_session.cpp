#include "analyzer/ort_session.hpp"

#include "core/logger.hpp"
#include "core/buffer_pool.hpp"
#include "core/gpu_buffer_pool.hpp"
#include "exec/stream_pool.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>
#include <filesystem>
#include "utils/cuda_ctx_guard.hpp"

#ifdef USE_ONNXRUNTIME
#include <onnxruntime_c_api.h>
#include <onnxruntime_cxx_api.h>
#if defined(USE_CUDA)
#if defined(__has_include)
#if __has_include(<cuda_runtime.h>)
#include <cuda_runtime.h>
#define VA_HAS_CUDA_RUNTIME 1
#else
#define VA_HAS_CUDA_RUNTIME 0
#endif
#else
#include <cuda_runtime.h>
#define VA_HAS_CUDA_RUNTIME 1
#endif
#else
#define VA_HAS_CUDA_RUNTIME 0
#endif
#endif

namespace va::analyzer {

#ifdef USE_ONNXRUNTIME

namespace {
inline const char* elemTypeToStr(ONNXTensorElementDataType t) {
    switch (t) {
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT: return "f32";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8: return "u8";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT8: return "i8";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT16: return "u16";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT16: return "i16";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT32: return "i32";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_INT64: return "i64";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_STRING: return "str";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_BOOL: return "bool";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16: return "f16";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_DOUBLE: return "f64";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT32: return "u32";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT64: return "u64";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_COMPLEX64: return "c64";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_COMPLEX128: return "c128";
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_BFLOAT16: return "bf16";
    default: return "unk";
    }
}

inline std::string shapeToStr(const std::vector<int64_t>& s) {
    std::string r; for (size_t i=0;i<s.size();++i){ r += (i?"x":""); r += std::to_string((long long)s[i]); } return r;
}
inline std::string toLower(std::string value) {
    std::transform(value.begin(), value.end(), value.begin(), [](unsigned char c) {
        return static_cast<char>(std::tolower(c));
    });
    return value;
}

#if VA_HAS_CUDA_RUNTIME
inline void releaseCudaBuffer(void*& pointer, size_t& capacity_bytes) {
    if (pointer) {
        cudaError_t err = cudaFree(pointer);
        if (err != cudaSuccess) {
            VA_LOG_WARN() << "cudaFree failed while releasing IoBinding buffer: " << cudaGetErrorString(err);
        }
        pointer = nullptr;
    }
    capacity_bytes = 0;
}

inline bool ensureCudaCapacity(void*& pointer, size_t& capacity_bytes, size_t required_bytes) {
    if (required_bytes == 0) {
        releaseCudaBuffer(pointer, capacity_bytes);
        return true;
    }
    if (pointer && capacity_bytes >= required_bytes) {
        return true;
    }

    releaseCudaBuffer(pointer, capacity_bytes);

    cudaError_t err = cudaMalloc(&pointer, required_bytes);
    if (err != cudaSuccess) {
        VA_LOG_C(::va::core::LogLevel::Error, "analyzer.ort")
            << "cudaMalloc failed while allocating IoBinding buffer (" << required_bytes
            << " bytes): " << cudaGetErrorString(err);
        pointer = nullptr;
        capacity_bytes = 0;
        return false;
    }
    capacity_bytes = required_bytes;
    return true;
}
#endif
} // namespace

namespace {
std::shared_ptr<Ort::Env> acquire_shared_env() {
    static std::mutex env_mutex;
    static std::weak_ptr<Ort::Env> weak_env;
    std::lock_guard<std::mutex> lock(env_mutex);
    auto env = weak_env.lock();
    if (!env) {
        env = std::make_shared<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, "VA_ONNX");
        weak_env = env;
    }
    return env;
}
} // namespace

struct OrtModelSession::Impl {
    Options options;
    std::shared_ptr<Ort::Env> env;
    std::unique_ptr<Ort::SessionOptions> session_options;
    std::unique_ptr<Ort::Session> session;
    std::unique_ptr<Ort::IoBinding> io_binding;
    std::vector<std::string> input_names_storage;
    std::vector<const char*> input_names;
    std::vector<std::string> output_names_storage;
    std::vector<const char*> output_names;
    std::vector<Ort::Value> last_outputs;
    bool use_gpu {false};
    std::mutex mutex;
#if VA_HAS_CUDA_RUNTIME
    void* io_input_device_buffer {nullptr};
    size_t io_input_capacity_bytes {0};
    std::unique_ptr<va::core::GpuBufferPool> device_pool;
    // ORT 计算流（与预处理 TLS 流一致）
    cudaStream_t ort_stream {nullptr};
#endif
    std::string resolved_provider {"cpu"};
    bool io_binding_enabled {false};
    bool device_binding_active {false};
    bool cpu_fallback {false};
    // host staging
    std::unique_ptr<va::core::HostBufferPool> host_pool;
    std::size_t host_pool_block_bytes {0};
    std::vector<va::core::HostBufferPool::Memory> staged_outputs;
};

OrtModelSession::OrtModelSession() = default;
OrtModelSession::~OrtModelSession() {
#if VA_HAS_CUDA_RUNTIME
    if (impl_) {
        std::scoped_lock lock(impl_->mutex);
        releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
        impl_->device_pool.reset();
        // 注意：StreamPool 持有 TLS 流的生命周期；此处不销毁 TLS 流
        impl_->ort_stream = nullptr;
    }
#endif
}

void OrtModelSession::setOptions(const Options& options) {
    if (!impl_) {
        impl_ = std::make_unique<Impl>();
    }
    std::scoped_lock lock(impl_->mutex);
    impl_->options = options;
}

bool OrtModelSession::loadModel(const std::string& model_path, bool use_gpu) {
    if (!impl_) {
        impl_ = std::make_unique<Impl>();
    }

    std::scoped_lock lock(impl_->mutex);

    if (!impl_->env) {
        impl_->env = acquire_shared_env();
    }

    impl_->session_options = std::make_unique<Ort::SessionOptions>();
    impl_->session_options->SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    impl_->session_options->SetIntraOpNumThreads(1);

    if (impl_->options.enable_profiling) {
        impl_->session_options->EnableProfiling(ORT_TSTR("ort_profile_"));
    }

    std::string provider = toLower(impl_->options.provider);
    const std::string initial_provider = provider;
    if (provider == "ort-trt" || provider == "ort_tensor_rt" || provider == "ort-tensorrt") {
        provider = "tensorrt";
    } else if (provider == "ort-cuda" || provider == "ort-gpu") {
        provider = "cuda";
    } else if (provider == "ort-cpu") {
        provider = "cpu";
    }
    // Normalize RTX alias
    if (provider == "nv_tensorrt_rtx" || provider == "tensorrt_rtx" || provider == "rtx") {
        // 当前不实现 RTX EP：将 RTX 请求视为常规 TensorRT
        provider = "tensorrt";
    }
    bool gpu_requested = use_gpu || provider == "cuda" || provider == "gpu" || provider == "tensorrt";
    impl_->use_gpu = gpu_requested;

    bool provider_appended = false;
    try {
#if defined(USE_CUDA)
        // 不尝试 RTX EP
        if (!provider_appended && provider == "tensorrt") {
            const OrtApi& api = Ort::GetApi();
            OrtTensorRTProviderOptionsV2* trt_options = nullptr;
            try {
                Ort::ThrowOnError(api.CreateTensorRTProviderOptions(&trt_options));

                // 先收集键值对，结束后再生成 char* 数组，避免 vector 重新分配导致 c_str() 失效
                struct KV { const char* key; std::string val; };
                std::vector<KV> kvs; kvs.reserve(24);
                kvs.push_back({"device_id", std::to_string(impl_->options.device_id)});
                kvs.push_back({"trt_fp16_enable", impl_->options.tensorrt_fp16 ? "1" : "0"});
                kvs.push_back({"trt_int8_enable", impl_->options.tensorrt_int8 ? "1" : "0"});
                // 启用 TensorRT 引擎与时序缓存，首次构建可能较久，缓存后显著加速
                std::string cache_dir = "/app/.ort_trt_cache";
                try { std::filesystem::create_directories(cache_dir); std::filesystem::create_directories(cache_dir + "/timing"); } catch (...) {}
                kvs.push_back({"trt_engine_cache_enable", "1"});
                kvs.push_back({"trt_engine_cache_path", cache_dir});
                kvs.push_back({"trt_timing_cache_enable", "1"});
                kvs.push_back({"trt_timing_cache_path", cache_dir + "/timing"});
                // 可选：串行构建（降低资源峰值）；默认关闭
                if (impl_->options.tensorrt_force_sequential_build) {
                    kvs.push_back({"trt_force_sequential_engine_build", "1"});
                }
                if (impl_->options.tensorrt_workspace_mb > 0) {
                    size_t workspace_bytes = static_cast<size_t>(impl_->options.tensorrt_workspace_mb) * 1024ull * 1024ull;
                    kvs.push_back({"trt_max_workspace_size", std::to_string(workspace_bytes)});
                }
                if (impl_->options.tensorrt_max_partition_iterations > 0) {
                    kvs.push_back({"trt_max_partition_iterations", std::to_string(impl_->options.tensorrt_max_partition_iterations)});
                }
                if (impl_->options.tensorrt_min_subgraph_size > 0) {
                    kvs.push_back({"trt_min_subgraph_size", std::to_string(impl_->options.tensorrt_min_subgraph_size)});
                }
                if (!impl_->options.tensorrt_profile_min_shapes.empty()) {
                    kvs.push_back({"trt_profile_min_shapes", impl_->options.tensorrt_profile_min_shapes});
                }
                if (!impl_->options.tensorrt_profile_opt_shapes.empty()) {
                    kvs.push_back({"trt_profile_opt_shapes", impl_->options.tensorrt_profile_opt_shapes});
                }
                if (!impl_->options.tensorrt_profile_max_shapes.empty()) {
                    kvs.push_back({"trt_profile_max_shapes", impl_->options.tensorrt_profile_max_shapes});
                }
                if (impl_->options.tensorrt_builder_optimization_level >= 0) {
                    kvs.push_back({"trt_builder_optimization_level", std::to_string(impl_->options.tensorrt_builder_optimization_level)});
                }
                if (impl_->options.tensorrt_auxiliary_streams >= 0) {
                    kvs.push_back({"trt_auxiliary_streams", std::to_string(impl_->options.tensorrt_auxiliary_streams)});
                }
                if (impl_->options.tensorrt_detailed_build_log) {
                    kvs.push_back({"trt_detailed_build_log", "1"});
                }

                std::vector<const char*> option_keys; option_keys.reserve(kvs.size());
                std::vector<const char*> option_values; option_values.reserve(kvs.size());
                for (auto& kv : kvs) { option_keys.push_back(kv.key); option_values.push_back(kv.val.c_str()); }

                if (!option_keys.empty()) {
                    Ort::ThrowOnError(api.UpdateTensorRTProviderOptions(trt_options,
                                                                        option_keys.data(),
                                                                        option_values.data(),
                                                                        option_keys.size()));
                }

                Ort::ThrowOnError(api.SessionOptionsAppendExecutionProvider_TensorRT_V2(*impl_->session_options, trt_options));
                provider_appended = true;
                impl_->use_gpu = true;
                provider = "tensorrt";
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort")
                    << "TensorRT EP(V2) appended device=" << impl_->options.device_id
                    << " cache_path='" << cache_dir << "'";
            } catch (const Ort::Exception& ex) {
                VA_LOG_WARN() << "Failed to configure TensorRT provider: " << ex.what() << ". Falling back to CUDA.";
                provider = "cuda";
                provider_appended = false;
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "Failed to configure TensorRT provider: " << ex.what() << ". Falling back to CUDA.";
                provider = "cuda";
                provider_appended = false;
            }

            if (trt_options) {
                api.ReleaseTensorRTProviderOptions(trt_options);
            }
        }
#else
        if (provider == "tensorrt") {
            VA_LOG_WARN() << "TensorRT provider requested but CUDA support is not compiled. Falling back to CPU.";
            provider = "cpu";
        }
#endif

        if (provider == "gpu") {
            provider = "cuda";
        }

        if (!provider_appended && (impl_->use_gpu || provider == "cuda")) {
#if defined(USE_CUDA)
            // Make sure the current thread has CUDA primary context bound
            va::utils::ensure_cuda_ready(impl_->options.device_id);
            // 统一 ORT 计算流：使用 CUDA EP V2，并设置 user_compute_stream 为当前 TLS 流
            const OrtApi& api = Ort::GetApi();
            OrtCUDAProviderOptionsV2* cuda_v2 = nullptr;
            try {
                Ort::ThrowOnError(api.CreateCUDAProviderOptions(&cuda_v2));
                // 统一 ORT 计算流：优先使用外部传入的 user_stream，否则回退到全局 TLS 流
                if (impl_->options.user_stream) {
                    impl_->ort_stream = reinterpret_cast<cudaStream_t>(impl_->options.user_stream);
                } else {
                    impl_->ort_stream = va::exec::StreamPool::instance().tls();
                }
                std::vector<std::string> opt_storage; opt_storage.reserve(8);
                std::vector<const char*> keys;   keys.reserve(8);
                std::vector<const char*> values; values.reserve(8);
                opt_storage.emplace_back(std::to_string(impl_->options.device_id));
                keys.emplace_back("device_id"); values.emplace_back(opt_storage.back().c_str());
                // 不在默认流复制，改用用户计算流
                opt_storage.emplace_back("0"); keys.emplace_back("do_copy_in_default_stream"); values.emplace_back(opt_storage.back().c_str());
                // 传入用户计算流指针
                opt_storage.emplace_back(std::to_string(reinterpret_cast<uintptr_t>(impl_->ort_stream)));
                keys.emplace_back("user_compute_stream"); values.emplace_back(opt_storage.back().c_str());
                Ort::ThrowOnError(api.UpdateCUDAProviderOptions(cuda_v2, keys.data(), values.data(), keys.size()));
                Ort::ThrowOnError(api.SessionOptionsAppendExecutionProvider_CUDA_V2(*impl_->session_options, cuda_v2));
                provider_appended = true;
                impl_->use_gpu = true;
                provider = "cuda";
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort")
                    << "CUDA EP(V2) appended device=" << impl_->options.device_id
                    << " user_stream=0x" << std::hex << reinterpret_cast<uintptr_t>(impl_->ort_stream) << std::dec;
            } catch (const Ort::Exception& ex) {
                VA_LOG_WARN() << "Append CUDA EP(V2) failed: " << ex.what() << "; fallback to legacy EP.";
                if (cuda_v2) api.ReleaseCUDAProviderOptions(cuda_v2);
                // 退回旧 API
                OrtCUDAProviderOptions cuda_opts{};
                cuda_opts.device_id = impl_->options.device_id;
                cuda_opts.gpu_mem_limit = SIZE_MAX;
                cuda_opts.arena_extend_strategy = 1;
                cuda_opts.cudnn_conv_algo_search = OrtCudnnConvAlgoSearchExhaustive;
                cuda_opts.do_copy_in_default_stream = 1;
                impl_->session_options->AppendExecutionProvider_CUDA(cuda_opts);
                provider_appended = true;
                impl_->use_gpu = true;
                provider = "cuda";
            } catch (...) {
                if (cuda_v2) api.ReleaseCUDAProviderOptions(cuda_v2);
                throw;
            }
            if (cuda_v2) api.ReleaseCUDAProviderOptions(cuda_v2);
            provider_appended = true;
            impl_->use_gpu = true;
            provider = "cuda";
#else
            VA_LOG_WARN() << "CUDA provider requested but CUDA support is not compiled. Falling back to CPU.";
            impl_->use_gpu = false;
#endif
        }
    } catch (const std::exception& ex) {
        VA_LOG_WARN() << "Failed to configure requested execution provider: " << ex.what();
        provider_appended = false;
        impl_->use_gpu = false;
    }

    // If GPU was requested (use_gpu flag) but provider append failed and CPU fallback is disabled, fail fast
    if (!provider_appended && !impl_->options.allow_cpu_fallback && impl_->use_gpu) {
        VA_LOG_ERROR() << "Execution provider configuration failed and CPU fallback disabled.";
        loaded_ = false;
        return false;
    }

    // 不实现 RTX 严格要求：忽略 require_rtx_when_requested

    if (!provider_appended) {
        impl_->use_gpu = false;
    }

    try {
#ifdef _WIN32
        std::wstring wide_path(model_path.begin(), model_path.end());
        impl_->session = std::make_unique<Ort::Session>(*impl_->env, wide_path.c_str(), *impl_->session_options);
#else
        impl_->session = std::make_unique<Ort::Session>(*impl_->env, model_path.c_str(), *impl_->session_options);
#endif
    } catch (const Ort::Exception& ex) {
        VA_LOG_ERROR() << "ONNX Runtime failed to load model: " << ex.what();
        impl_->session.reset();
        loaded_ = false;
        return false;
    }

    Ort::AllocatorWithDefaultOptions allocator;
    impl_->input_names_storage.clear();
    impl_->input_names.clear();
    size_t input_count = impl_->session->GetInputCount();
    impl_->input_names_storage.reserve(input_count);
    impl_->input_names.reserve(input_count);
    for (size_t i = 0; i < input_count; ++i) {
        Ort::AllocatedStringPtr name = impl_->session->GetInputNameAllocated(i, allocator);
        impl_->input_names_storage.emplace_back(name.get());
        impl_->input_names.emplace_back(impl_->input_names_storage.back().c_str());
    }

    impl_->output_names_storage.clear();
    impl_->output_names.clear();
    size_t output_count = impl_->session->GetOutputCount();
    impl_->output_names_storage.reserve(output_count);
    impl_->output_names.reserve(output_count);
    for (size_t i = 0; i < output_count; ++i) {
        Ort::AllocatedStringPtr name = impl_->session->GetOutputNameAllocated(i, allocator);
        impl_->output_names_storage.emplace_back(name.get());
        impl_->output_names.emplace_back(impl_->output_names_storage.back().c_str());
    }

    if (output_count == 0) {
        try {
            VA_LOG_C(::va::core::LogLevel::Error, "analyzer.ort")
                << "load: model has zero outputs (path='" << model_path << "').";
        } catch (...) { /* ignore */ }
    }

    impl_->resolved_provider = provider_appended ? provider : std::string{"cpu"};
    impl_->cpu_fallback = gpu_requested && !provider_appended;

    // Summarize model IO after load
    try {
        size_t in0_rank = 0; std::vector<int64_t> in0_shape; const char* in0_dtype = "?";
        if (input_count > 0) {
            Ort::TypeInfo ti = impl_->session->GetInputTypeInfo(0);
            auto tt = ti.GetTensorTypeAndShapeInfo();
            in0_rank = tt.GetShape().size();
            in0_shape = tt.GetShape();
            in0_dtype = elemTypeToStr(tt.GetElementType());
        }
        VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort")
            << "load: provider_req='" << provider << "' resolved='" << impl_->resolved_provider
            << "' gpu_req=" << std::boolalpha << gpu_requested
            << " cpu_fallback=" << impl_->cpu_fallback
            << " inputs=" << input_count << " outputs=" << output_count
            << " in0_dtype=" << in0_dtype << " in0_shape=" << shapeToStr(in0_shape);
        // 额外：列出前若干输入/输出名，辅助校验导出是否包含 graph outputs
        try {
            std::string in_names, out_names;
            for (size_t i=0;i<input_count && i<8;i++) { if (i) in_names += ","; in_names += impl_->input_names_storage[i]; }
            for (size_t i=0;i<output_count && i<8;i++) { if (i) out_names += ","; out_names += impl_->output_names_storage[i]; }
            VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort")
                << "io.names in=[" << in_names << "] out=[" << out_names << "]"
                << " use_iob=" << std::boolalpha << impl_->options.use_io_binding
                << " allow_cpu_fallback=" << impl_->options.allow_cpu_fallback
                << " device_id=" << impl_->options.device_id;
        } catch (...) {}
    } catch (...) { /* best-effort */ }

    // Lightweight warmup: run N inference passes with a zero tensor on CPU memory.
    // Initializes EP kernels/graphs to reduce the first-frame latency.
    try {
        // Decide warmup runs: 0=disable, -1=auto, >0=fixed
        int runs_cfg = impl_->options.warmup_runs;
        // On TensorRT EP, skip auto warmup to avoid long engine build at startup
        if ((provider_appended ? provider : std::string{"cpu"}) == std::string{"tensorrt"} && runs_cfg < 0) {
            runs_cfg = 0; // auto -> off for TRT
            try {
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort")
                    << "[OrtWarmup] provider=tensorrt auto->off to avoid first-run engine build at startup.";
            } catch (...) { /* ignore */ }
        }
        Ort::AllocatorWithDefaultOptions warm_alloc;
        // Derive an input shape; replace dynamic dims with concrete values
        std::vector<int64_t> ishape;
        {
            Ort::TypeInfo ti = impl_->session->GetInputTypeInfo(0);
            auto tensor_info = ti.GetTensorTypeAndShapeInfo();
            ishape = tensor_info.GetShape();
            if (ishape.empty()) { ishape = {1,3,640,640}; }
            // Heuristics: if 4D and channel dim is 3, use 1x3x640x640; otherwise replace non-positive dims with 1
            if (ishape.size() == 4 && (ishape[1] == 3 || ishape[1] <= 0)) {
                if (ishape[0] <= 0) ishape[0] = 1;
                if (ishape[1] <= 0) ishape[1] = 3;
                if (ishape[2] <= 0) ishape[2] = 640;
                if (ishape[3] <= 0) ishape[3] = 640;
            } else {
                for (auto& d : ishape) if (d <= 0) d = 1;
            }
        }
        // Auto runs based on model_path hint or input area
        int runs = runs_cfg;
        if (runs_cfg < 0) {
            // Try parse model variant from path
            int suggested = 1;
            try {
                // Very rough heuristic by input size
                if (ishape.size() == 4) {
                    const int64_t H = ishape[2];
                    const int64_t W = ishape[3];
                    const int64_t area = H * W;
                    if (area >= 1024 * 1024) suggested = 3; // >= 1MP
                    else if (area >= 640 * 640) suggested = 2; // >= 640^2
                    else suggested = 1;
                }
            } catch (...) { suggested = 1; }
            runs = suggested;
        }
        if (runs == 0) {
            loaded_ = true;
            return true;
        }
        size_t elem = 1;
        for (auto d : ishape) { elem *= static_cast<size_t>(d); }
        std::vector<float> zeros(elem, 0.0f);
        Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
        Ort::Value in = Ort::Value::CreateTensor<float>(mem, zeros.data(), zeros.size(), ishape.data(), ishape.size());
        auto t0 = std::chrono::high_resolution_clock::now();
        for (int i = 0; i < runs; ++i) {
            (void)impl_->session->Run(Ort::RunOptions{nullptr},
                                      impl_->input_names.data(), &in, 1,
                                      impl_->output_names.data(), impl_->output_names.size());
        }
        auto t1 = std::chrono::high_resolution_clock::now();
        auto ms = std::chrono::duration_cast<std::chrono::milliseconds>(t1 - t0).count();
        VA_LOG_INFO() << "[OrtWarmup] runs=" << runs << " total_ms=" << ms << " avg_ms=" << (runs>0? (ms / runs) : 0)
                      << " shape=" << ishape[0] << "x" << (ishape.size()>1?ishape[1]:0) << "x"
                      << (ishape.size()>2?ishape[2]:0) << "x" << (ishape.size()>3?ishape[3]:0);
    } catch (const std::exception& ex) {
        VA_LOG_WARN() << "[OrtWarmup] skipped due to error: " << ex.what();
    }

    if (impl_->options.use_io_binding && impl_->use_gpu) {
        try {
            impl_->io_binding = std::make_unique<Ort::IoBinding>(*impl_->session);
            VA_LOG_INFO() << "OrtModelSession IoBinding enabled (provider="
                          << (provider_appended ? provider : "cpu")
                          << ")";
#if VA_HAS_CUDA_RUNTIME
            // Initialize GPU buffer pool for input staging (optional initial hint)
            impl_->device_pool = std::make_unique<va::core::GpuBufferPool>(impl_->options.io_binding_input_bytes, 4);
#endif
            impl_->io_binding_enabled = true;
        } catch (const std::exception& ex) {
            VA_LOG_WARN() << "Failed to initialize IoBinding: " << ex.what();
            impl_->io_binding.reset();
#if VA_HAS_CUDA_RUNTIME
            releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
            impl_->device_pool.reset();
#endif
            impl_->io_binding_enabled = false;
            impl_->device_binding_active = false;
        }
    } else {
        impl_->io_binding.reset();
#if VA_HAS_CUDA_RUNTIME
        releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
        impl_->device_pool.reset();
#endif
        impl_->io_binding_enabled = false;
        impl_->device_binding_active = false;
    }

    impl_->device_binding_active = impl_->use_gpu;

    loaded_ = true;
    return true;
}

namespace {
core::TensorView makeTensorView(Ort::Value& value, bool on_gpu) {
    core::TensorView view;
    if (!value.IsTensor()) {
        return view;
    }

    Ort::TensorTypeAndShapeInfo shape_info = value.GetTensorTypeAndShapeInfo();
    view.shape = shape_info.GetShape();
    view.dtype = core::DType::F32;
    view.on_gpu = on_gpu;
    view.data = value.GetTensorMutableData<float>();
    return view;
}
}

bool OrtModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    if (!loaded_ || !impl_ || !impl_->session) {
        return false;
    }

    if (!input.data || input.shape.empty()) {
        return false;
    }

    std::scoped_lock lock(impl_->mutex);

    const size_t element_count = std::accumulate(input.shape.begin(), input.shape.end(), static_cast<size_t>(1), std::multiplies<size_t>());
    if (element_count == 0) {
        return false;
    }

    if (input.dtype != core::DType::F32) {
        VA_LOG_WARN() << "OrtModelSession only supports F32 tensors currently.";
        return false;
    }

    try {
        // Lazy-enable IoBinding if requested and GPU active but not yet created
        if (!impl_->io_binding && impl_->options.use_io_binding && impl_->use_gpu) {
            try {
                impl_->io_binding = std::make_unique<Ort::IoBinding>(*impl_->session);
                impl_->io_binding_enabled = true;
#if VA_HAS_CUDA_RUNTIME
                if (!impl_->device_pool) {
                    impl_->device_pool = std::make_unique<va::core::GpuBufferPool>(impl_->options.io_binding_input_bytes, 4);
                }
#endif
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.ort") << "IoBinding (lazy) enabled for run()";
            } catch (const std::exception& ex) {
                VA_LOG_WARN() << "IoBinding lazy init failed: " << ex.what() << "; continue without IoBinding.";
                impl_->io_binding.reset();
                impl_->io_binding_enabled = false;
            }
        }
        // Pre-run summary (once per throttle window)
        try {
            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run.in", 1000)
                << "in_shape=" << shapeToStr(input.shape)
                << " on_gpu=" << std::boolalpha << input.on_gpu
                << " provider=" << (impl_->resolved_provider.empty()?"cpu":impl_->resolved_provider)
                << " use_iob=" << (impl_->io_binding!=nullptr);
        } catch (...) { /* ignore */ }
        if (impl_->io_binding) {
            impl_->io_binding->ClearBoundInputs();
            impl_->io_binding->ClearBoundOutputs();

            std::vector<Ort::Value> input_holders;
            input_holders.reserve(1);

            bool bound_device_input = false;
#if VA_HAS_CUDA_RUNTIME
            va::core::GpuBufferPool::Memory pooled_input_mem{};
#endif

#if VA_HAS_CUDA_RUNTIME
            if (impl_->use_gpu && impl_->options.use_io_binding) {
                // Stage host F32 tensor to device buffer if needed
                const size_t bytes = element_count * sizeof(float);
                if (!input.on_gpu) {
                    void* dev_ptr = nullptr;
#if VA_HAS_CUDA_RUNTIME
                    if (impl_->device_pool) {
                        pooled_input_mem = impl_->device_pool->acquire(bytes);
                        dev_ptr = pooled_input_mem.ptr;
                    }
#endif
                    if (!dev_ptr) {
                        if (ensureCudaCapacity(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes, bytes)) {
                            dev_ptr = impl_->io_input_device_buffer;
                        }
                    }
#if VA_HAS_CUDA_RUNTIME
                    if (dev_ptr) {
                        // 使用 ORT 计算流进行 H2D，保证与推理同一 stream 顺序一致
                        cudaError_t err = cudaMemcpyAsync(dev_ptr, input.data, bytes, cudaMemcpyHostToDevice,
                                                          impl_->ort_stream ? impl_->ort_stream : 0);
                        if (err == cudaSuccess) {
                            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run.bind", 1000)
                                << "path=iob H2D bytes=" << bytes;
                            Ort::MemoryInfo input_mem_dev("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                            input_holders.emplace_back(Ort::Value::CreateTensor<float>(
                                input_mem_dev,
                                static_cast<float*>(dev_ptr),
                                element_count,
                                const_cast<int64_t*>(input.shape.data()),
                                input.shape.size()));
                            bound_device_input = true;
                        } else {
                            VA_LOG_WARN() << "cudaMemcpy H2D failed: " << cudaGetErrorString(err) << ", falling back to CPU input bind";
                        }
                    }
#endif
                } else {
                    // 输入已在 GPU：进行 D2D 拷贝至会话缓冲，使用 ORT 计算流保证可见性
                    void* dev_ptr = nullptr;
                    if (impl_->device_pool) {
                        pooled_input_mem = impl_->device_pool->acquire(bytes);
                        dev_ptr = pooled_input_mem.ptr;
                    }
                    if (!dev_ptr) {
                        if (ensureCudaCapacity(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes, bytes)) {
                            dev_ptr = impl_->io_input_device_buffer;
                        }
                    }
                    if (dev_ptr) {
                        cudaError_t err = cudaMemcpyAsync(dev_ptr, input.data, bytes, cudaMemcpyDeviceToDevice,
                                                          impl_->ort_stream ? impl_->ort_stream : 0);
                        if (err == cudaSuccess) {
                            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run.bind", 1000)
                                << "path=iob D2D bytes=" << bytes;
                            Ort::MemoryInfo input_mem_dev("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                            input_holders.emplace_back(Ort::Value::CreateTensor<float>(
                                input_mem_dev,
                                static_cast<float*>(dev_ptr),
                                element_count,
                                const_cast<int64_t*>(input.shape.data()),
                                input.shape.size()));
                            bound_device_input = true;
                        }
                    }
                }
            }
#endif

            if (!bound_device_input) {
                Ort::MemoryInfo input_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                if (impl_->options.use_io_binding && impl_->use_gpu && impl_->options.prefer_pinned_memory) {
                    input_mem = Ort::MemoryInfo("CudaPinned", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeCPU);
                }

                input_holders.emplace_back(Ort::Value::CreateTensor<float>(
                    input_mem,
                    static_cast<float*>(input.data),
                    element_count,
                    const_cast<int64_t*>(input.shape.data()),
                    input.shape.size()));
            }

            impl_->device_binding_active = impl_->use_gpu;

            const char* input_name = impl_->input_names.empty() ? "input" : impl_->input_names.front();
            impl_->io_binding->BindInput(input_name, input_holders.front());

            const bool bind_outputs_to_device = impl_->options.use_io_binding && impl_->use_gpu && (impl_->options.stage_device_outputs || impl_->options.device_output_views);
            VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run.bind", 1000)
                << "bind_outputs_to_device=" << std::boolalpha << bind_outputs_to_device
                << " stage_outputs=" << impl_->options.stage_device_outputs
                << " device_views=" << impl_->options.device_output_views;
            for (const char* output_name : impl_->output_names) {
                if (bind_outputs_to_device) {
#if VA_HAS_CUDA_RUNTIME
                    Ort::MemoryInfo out_mem_dev("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                    impl_->io_binding->BindOutput(output_name, out_mem_dev);
#else
                    Ort::MemoryInfo out_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                    impl_->io_binding->BindOutput(output_name, out_mem);
#endif
                } else {
                    // Safe baseline: bind outputs to CPU; let ORT stage device->host internally.
                    Ort::MemoryInfo out_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                    impl_->io_binding->BindOutput(output_name, out_mem);
                }
            }

            Ort::RunOptions run_opts;
            try {
                VA_LOG_THROTTLED(::va::core::LogLevel::Info, "ort.run.start", 1000)
                    << "provider=" << (impl_->resolved_provider.empty()?"cpu":impl_->resolved_provider)
                    << " iob=" << (impl_->io_binding!=nullptr)
                    << " dev_bind=" << impl_->device_binding_active
                    << " in_shape=" << shapeToStr(input.shape)
                    << " in_on_gpu=" << input.on_gpu;
            } catch (...) {}
            impl_->session->Run(run_opts, *impl_->io_binding);
            impl_->io_binding->SynchronizeOutputs();

            impl_->last_outputs = impl_->io_binding->GetOutputValues();
            outputs.clear();
            outputs.reserve(impl_->last_outputs.size());
            impl_->staged_outputs.clear();

            // 运行时输出形状日志（节流）
            try {
                auto lvl = ::va::core::LogLevel::Debug; // default
                auto n = impl_->last_outputs.size();
                if (n > 0) {
                    std::string shapes;
                    for (size_t i=0;i<n && i<3;i++) {
                        auto& v = impl_->last_outputs[i];
                        if (!v.IsTensor()) { shapes += (i? ",":""); shapes += "non-tensor"; continue; }
                        auto info = v.GetTensorTypeAndShapeInfo(); auto s = info.GetShape();
                        if (i) shapes += ","; for (size_t k=0;k<s.size();++k){ shapes += (k?"x":""); shapes += std::to_string((long long)s[k]); }
                    }
                    VA_LOG_THROTTLED(lvl, "ort.run", 1000) << "outputs=" << n << " out0..2_shapes=" << shapes
                        << " provider=" << (impl_->resolved_provider.empty()?"cpu":impl_->resolved_provider)
                        << " io_bind=" << std::boolalpha << impl_->io_binding_enabled
                        << " dev_bind=" << impl_->device_binding_active;
                } else {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run", 1000) << "outputs=0";
                }
            } catch (...) { /* best-effort */ }

            const bool prefer_device_views = impl_->options.device_output_views && impl_->use_gpu && impl_->options.use_io_binding && bind_outputs_to_device;
            const bool stage_outputs = impl_->options.stage_device_outputs && impl_->use_gpu && impl_->options.use_io_binding && !prefer_device_views;
            if (prefer_device_views) {
                // Expose device-backed outputs without staging; preserve true dtype
                for (auto& value : impl_->last_outputs) {
                    if (!value.IsTensor()) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                    Ort::TensorTypeAndShapeInfo info = value.GetTensorTypeAndShapeInfo();
                    core::TensorView view;
                    view.data = const_cast<void*>(value.GetTensorRawData());
                    view.shape = info.GetShape();
                    switch (info.GetElementType()) {
                        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:
                            view.dtype = core::DType::F32; break;
                        case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16:
                            view.dtype = core::DType::F16; break;
                        default:
                            view.dtype = core::DType::F32; break;
                    }
                    view.on_gpu = true;
                    outputs.emplace_back(std::move(view));
                }
            } else if (stage_outputs) {
                if (!impl_->host_pool) {
                    impl_->host_pool_block_bytes = impl_->options.tensor_host_pool_bytes;
                    if (impl_->host_pool_block_bytes == 0 && !impl_->last_outputs.empty()) {
                        try {
                            Ort::TensorTypeAndShapeInfo info = impl_->last_outputs.front().GetTensorTypeAndShapeInfo();
                            auto shape = info.GetShape();
                            size_t count = 1;
                            for (auto d : shape) count *= static_cast<size_t>(d > 0 ? d : 1);
                            impl_->host_pool_block_bytes = count * sizeof(float);
                        } catch (...) {
                            impl_->host_pool_block_bytes = 0;
                        }
                    }
                    impl_->host_pool = std::make_unique<va::core::HostBufferPool>(impl_->host_pool_block_bytes, 8);
                }

                for (auto& value : impl_->last_outputs) {
                    if (!value.IsTensor()) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                    Ort::TensorTypeAndShapeInfo info = value.GetTensorTypeAndShapeInfo();
                    auto shape = info.GetShape();
                    size_t count = 1;
                    for (auto d : shape) count *= static_cast<size_t>(d > 0 ? d : 1);
                    size_t bytes = count * sizeof(float); // host float buffer size

                    auto mem = impl_->host_pool->acquire(bytes);
                    if (!mem.ptr || mem.bytes < bytes) {
                        outputs.emplace_back(makeTensorView(value, false));
                        continue;
                    }
#if VA_HAS_CUDA_RUNTIME
                    if (bind_outputs_to_device) {
                        const void* src_dev = value.GetTensorRawData();
                        auto et = info.GetElementType();
                        if (et == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
                            cudaError_t err = cudaMemcpy(mem.ptr, src_dev, bytes, cudaMemcpyDeviceToHost);
                            if (err != cudaSuccess) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                        } else if (et == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
                            // Copy as IEEE754 binary16 to host then convert to float
                            std::vector<uint16_t> host_half(count);
                            size_t half_bytes = count * sizeof(uint16_t);
                            cudaError_t err = cudaMemcpy(host_half.data(), src_dev, half_bytes, cudaMemcpyDeviceToHost);
                            if (err != cudaSuccess) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                            auto h2f = [](uint16_t h)->float {
                                uint32_t s = (h & 0x8000u) << 16;
                                uint32_t e = (h & 0x7C00u) >> 10;
                                uint32_t f = (h & 0x03FFu);
                                uint32_t out_e, out_f;
                                if (e == 0) {
                                    if (f == 0) { out_e = 0; out_f = 0; }
                                    else {
                                        // subnormal
                                        e = 1; while ((f & 0x0400u) == 0) { f <<= 1; e--; }
                                        f &= 0x03FFu;
                                        out_e = e + (127 - 15);
                                        out_f = f << 13;
                                    }
                                } else if (e == 31) { // Inf/NaN
                                    out_e = 255; out_f = f ? (f << 13) : 0;
                                } else {
                                    out_e = e + (127 - 15);
                                    out_f = f << 13;
                                }
                                uint32_t bits = s | (out_e << 23) | out_f;
                                float result; std::memcpy(&result, &bits, sizeof(result)); return result;
                            };
                            float* dst = reinterpret_cast<float*>(mem.ptr);
                            for (size_t i=0;i<count;++i) dst[i] = h2f(host_half[i]);
                        } else {
                            // Unsupported dtype: fallback to raw view construction
                            outputs.emplace_back(makeTensorView(value, false));
                            continue;
                        }
                    } else
#endif
                    {
                        auto et = info.GetElementType();
                        if (et == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT) {
                            const float* src = nullptr;
                            try { src = value.GetTensorData<float>(); } catch (...) { src = nullptr; }
                            if (!src) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                            std::memcpy(mem.ptr, src, bytes);
                        } else if (et == ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16) {
                            const uint16_t* src = reinterpret_cast<const uint16_t*>(value.GetTensorRawData());
                            if (!src) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                            auto h2f = [](uint16_t h)->float {
                                uint32_t s = (h & 0x8000u) << 16;
                                uint32_t e = (h & 0x7C00u) >> 10;
                                uint32_t f = (h & 0x03FFu);
                                uint32_t out_e, out_f;
                                if (e == 0) {
                                    if (f == 0) { out_e = 0; out_f = 0; }
                                    else { e = 1; while ((f & 0x0400u) == 0) { f <<= 1; e--; } f &= 0x03FFu; out_e = e + (127 - 15); out_f = f << 13; }
                                } else if (e == 31) { out_e = 255; out_f = f ? (f << 13) : 0; }
                                else { out_e = e + (127 - 15); out_f = f << 13; }
                                uint32_t bits = s | (out_e << 23) | out_f; float r; std::memcpy(&r, &bits, sizeof(r)); return r;
                            };
                            float* dst = reinterpret_cast<float*>(mem.ptr);
                            for (size_t i=0;i<count;++i) dst[i] = h2f(src[i]);
                        } else {
                            outputs.emplace_back(makeTensorView(value, false));
                            continue;
                        }
                    }

                    core::TensorView view;
                    view.data = mem.ptr;
                    view.shape = std::move(shape);
                    view.dtype = core::DType::F32;
                    view.on_gpu = false;
                    outputs.emplace_back(view);
                    impl_->staged_outputs.emplace_back(std::move(mem));
                }
            } else {
                for (auto& value : impl_->last_outputs) {
                    outputs.emplace_back(makeTensorView(value, false));
                }
            }

            impl_->io_binding->ClearBoundInputs();
            impl_->io_binding->ClearBoundOutputs();
#if VA_HAS_CUDA_RUNTIME
            if (pooled_input_mem.ptr && impl_->device_pool) {
                impl_->device_pool->release(std::move(pooled_input_mem));
            }
#endif
        } else {
            // Non-IoBinding path. If input is on GPU, stage to host before creating CPU tensor.
            std::vector<float> host_input; // keep alive until after Run()
            const void* input_data_ptr = input.data;
#if VA_HAS_CUDA_RUNTIME
            if (input.on_gpu && input.data && element_count > 0) {
                try {
                    host_input.resize(element_count);
                    cudaError_t err = cudaMemcpy(host_input.data(), input.data, element_count*sizeof(float), cudaMemcpyDeviceToHost);
                    if (err == cudaSuccess) {
                        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run.bind", 1000)
                            << "path=non-iob D2H bytes=" << (element_count*sizeof(float));
                        input_data_ptr = host_input.data();
                    } else {
                        VA_LOG_WARN() << "Non-IOB path: cudaMemcpy D2H failed, falling back to original pointer (may be invalid for CPU)";
                    }
                } catch (...) {
                    // If allocation failed, continue with original pointer (may fail in ORT)
                }
            }
#endif
            Ort::MemoryInfo input_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
            Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
                input_mem,
                const_cast<float*>(static_cast<const float*>(input_data_ptr)),
                element_count,
                const_cast<int64_t*>(input.shape.data()),
                input.shape.size());

            impl_->last_outputs = impl_->session->Run(Ort::RunOptions{nullptr},
                                                       impl_->input_names.data(),
                                                       &input_tensor,
                                                       1,
                                                       impl_->output_names.data(),
                                                       impl_->output_names.size());
            outputs.clear();
            outputs.reserve(impl_->last_outputs.size());
            for (auto& value : impl_->last_outputs) {
                outputs.emplace_back(makeTensorView(value, false));
            }
            // Log outputs (non-IoBinding)
            try {
                auto n = impl_->last_outputs.size();
                if (n > 0) {
                    std::string shapes;
                    for (size_t i=0;i<n && i<3;i++) {
                        auto& v = impl_->last_outputs[i];
                        if (!v.IsTensor()) { shapes += (i? ",":""); shapes += "non-tensor"; continue; }
                        auto info = v.GetTensorTypeAndShapeInfo(); auto s = info.GetShape();
                        if (i) shapes += ","; for (size_t k=0;k<s.size();++k){ shapes += (k?"x":""); shapes += std::to_string((long long)s[k]); }
                    }
                    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run", 1000) << "outputs=" << n << " out0..2_shapes=" << shapes
                        << " provider=" << (impl_->resolved_provider.empty()?"cpu":impl_->resolved_provider)
                        << " io_bind=" << std::boolalpha << impl_->io_binding_enabled
                        << " dev_bind=" << impl_->device_binding_active;
                } else {
                    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ort.run", 1000) << "outputs=0 (non-IOB)";
                }
            } catch (...) { /* ignore */ }
        }
        if (!impl_->io_binding) {
            impl_->device_binding_active = false;
        } else if (impl_->use_gpu) {
            impl_->device_binding_active = true;
        }
    } catch (const Ort::Exception& ex) {
        VA_LOG_ERROR() << "OrtModelSession inference failed: " << ex.what();
        return false;
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "OrtModelSession inference failed: " << ex.what();
        return false;
    }

    return true;
}

OrtModelSession::RuntimeInfo OrtModelSession::runtimeInfo() const {
    RuntimeInfo info;
    if (!impl_) {
        return info;
    }
    std::scoped_lock lock(impl_->mutex);
    info.provider = impl_->resolved_provider;
    info.gpu_active = impl_->use_gpu;
    info.io_binding_active = impl_->io_binding_enabled && impl_->io_binding != nullptr;
    info.device_binding_active = impl_->device_binding_active;
    info.cpu_fallback = impl_->cpu_fallback;
    return info;
}

std::vector<std::string> OrtModelSession::outputNames() const {
#ifdef USE_ONNXRUNTIME
    std::vector<std::string> names;
    if (!impl_) return names;
    std::scoped_lock lock(impl_->mutex);
    names = impl_->output_names_storage;
    return names;
#else
    return {};
#endif
}

IModelSession::ModelRuntimeInfo OrtModelSession::getRuntimeInfo() const {
    IModelSession::ModelRuntimeInfo out;
    auto ri = runtimeInfo();
    out.provider = std::move(ri.provider);
    out.gpu_active = ri.gpu_active;
    out.io_binding = ri.io_binding_active;
    out.device_binding = ri.device_binding_active;
    out.cpu_fallback = ri.cpu_fallback;
    return out;
}

#else // USE_ONNXRUNTIME

struct OrtModelSession::Impl {};

OrtModelSession::OrtModelSession() = default;
OrtModelSession::~OrtModelSession() = default;

bool OrtModelSession::loadModel(const std::string&, bool) {
    loaded_ = true;
    return true;
}

bool OrtModelSession::run(const core::TensorView&, std::vector<core::TensorView>& outputs) {
    outputs.clear();
    return loaded_;
}

OrtModelSession::RuntimeInfo OrtModelSession::runtimeInfo() const {
    return {};
}

std::vector<std::string> OrtModelSession::outputNames() const {
    return {};
}

#endif // USE_ONNXRUNTIME

} // namespace va::analyzer
