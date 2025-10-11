#include "analyzer/ort_session.hpp"

#include "core/logger.hpp"
#include "core/buffer_pool.hpp"
#include "core/gpu_buffer_pool.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>

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

struct OrtModelSession::Impl {
    Options options;
    std::unique_ptr<Ort::Env> env;
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
        impl_->env = std::make_unique<Ort::Env>(ORT_LOGGING_LEVEL_WARNING, "VA_ONNX");
    }

    impl_->session_options = std::make_unique<Ort::SessionOptions>();
    impl_->session_options->SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
    impl_->session_options->SetIntraOpNumThreads(1);

    if (impl_->options.enable_profiling) {
        impl_->session_options->EnableProfiling(L"ort_profile_");
    }

    std::string provider = toLower(impl_->options.provider);
    if (provider == "ort-trt" || provider == "ort_tensor_rt" || provider == "ort-tensorrt") {
        provider = "tensorrt";
    } else if (provider == "ort-cuda" || provider == "ort-gpu") {
        provider = "cuda";
    } else if (provider == "ort-cpu") {
        provider = "cpu";
    }
    bool gpu_requested = use_gpu || provider == "cuda" || provider == "gpu" || provider == "tensorrt";
    impl_->use_gpu = gpu_requested;

    bool provider_appended = false;
    try {
#if defined(USE_CUDA)
        if (!provider_appended && provider == "tensorrt") {
            const OrtApi& api = Ort::GetApi();
            OrtTensorRTProviderOptionsV2* trt_options = nullptr;
            try {
                Ort::ThrowOnError(api.CreateTensorRTProviderOptions(&trt_options));

                std::vector<std::string> option_storage;
                std::vector<const char*> option_keys;
                std::vector<const char*> option_values;

                option_storage.emplace_back(std::to_string(impl_->options.device_id));
                option_keys.emplace_back("device_id");
                option_values.emplace_back(option_storage.back().c_str());

                option_storage.emplace_back(impl_->options.tensorrt_fp16 ? "1" : "0");
                option_keys.emplace_back("trt_fp16_enable");
                option_values.emplace_back(option_storage.back().c_str());

                option_storage.emplace_back(impl_->options.tensorrt_int8 ? "1" : "0");
                option_keys.emplace_back("trt_int8_enable");
                option_values.emplace_back(option_storage.back().c_str());

                if (impl_->options.tensorrt_workspace_mb > 0) {
                    size_t workspace_bytes = static_cast<size_t>(impl_->options.tensorrt_workspace_mb) * 1024ull * 1024ull;
                    option_storage.emplace_back(std::to_string(workspace_bytes));
                    option_keys.emplace_back("trt_max_workspace_size");
                    option_values.emplace_back(option_storage.back().c_str());
                }
                if (impl_->options.tensorrt_max_partition_iterations > 0) {
                    option_storage.emplace_back(std::to_string(impl_->options.tensorrt_max_partition_iterations));
                    option_keys.emplace_back("trt_max_partition_iterations");
                    option_values.emplace_back(option_storage.back().c_str());
                }
                if (impl_->options.tensorrt_min_subgraph_size > 0) {
                    option_storage.emplace_back(std::to_string(impl_->options.tensorrt_min_subgraph_size));
                    option_keys.emplace_back("trt_min_subgraph_size");
                    option_values.emplace_back(option_storage.back().c_str());
                }

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

    if (!provider_appended && !impl_->options.allow_cpu_fallback && impl_->use_gpu) {
        VA_LOG_ERROR() << "Execution provider configuration failed and CPU fallback disabled.";
        loaded_ = false;
        return false;
    }

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

    impl_->resolved_provider = provider_appended ? provider : std::string{"cpu"};
    impl_->cpu_fallback = gpu_requested && !provider_appended;

    // Lightweight warmup: run N inference passes with a zero tensor on CPU memory.
    // Initializes EP kernels/graphs to reduce the first-frame latency.
    try {
        // Decide warmup runs: 0=disable, -1=auto, >0=fixed
        int runs_cfg = impl_->options.warmup_runs;
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
                        cudaError_t err = cudaMemcpy(dev_ptr, input.data, bytes, cudaMemcpyHostToDevice);
                        if (err == cudaSuccess) {
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
                    // Caller-provided device pointer (best-effort)
                    Ort::MemoryInfo input_mem_dev("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                    input_holders.emplace_back(Ort::Value::CreateTensor<float>(
                        input_mem_dev,
                        static_cast<float*>(input.data),
                        element_count,
                        const_cast<int64_t*>(input.shape.data()),
                        input.shape.size()));
                    bound_device_input = true;
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
            impl_->session->Run(run_opts, *impl_->io_binding);
            impl_->io_binding->SynchronizeOutputs();

            impl_->last_outputs = impl_->io_binding->GetOutputValues();
            outputs.clear();
            outputs.reserve(impl_->last_outputs.size());
            impl_->staged_outputs.clear();

            const bool prefer_device_views = impl_->options.device_output_views && impl_->use_gpu && impl_->options.use_io_binding && bind_outputs_to_device;
            const bool stage_outputs = impl_->options.stage_device_outputs && impl_->use_gpu && impl_->options.use_io_binding && !prefer_device_views;
            if (prefer_device_views) {
                // Expose device-backed outputs without staging
                for (auto& value : impl_->last_outputs) {
                    if (!value.IsTensor()) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                    Ort::TensorTypeAndShapeInfo info = value.GetTensorTypeAndShapeInfo();
                    core::TensorView view;
                    view.data = const_cast<void*>(value.GetTensorRawData());
                    view.shape = info.GetShape();
                    view.dtype = core::DType::F32;
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
                    size_t bytes = count * sizeof(float);

                    auto mem = impl_->host_pool->acquire(bytes);
                    if (!mem.ptr || mem.bytes < bytes) {
                        outputs.emplace_back(makeTensorView(value, false));
                        continue;
                    }
#if VA_HAS_CUDA_RUNTIME
                    if (bind_outputs_to_device) {
                        const void* src_dev = value.GetTensorRawData();
                        cudaError_t err = cudaMemcpy(mem.ptr, src_dev, bytes, cudaMemcpyDeviceToHost);
                        if (err != cudaSuccess) {
                            outputs.emplace_back(makeTensorView(value, false));
                            continue;
                        }
                    } else
#endif
                    {
                        const float* src = nullptr;
                        try { src = value.GetTensorData<float>(); } catch (...) { src = nullptr; }
                        if (!src) { outputs.emplace_back(makeTensorView(value, false)); continue; }
                        std::memcpy(mem.ptr, src, bytes);
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
            Ort::MemoryInfo input_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
            Ort::Value input_tensor = Ort::Value::CreateTensor<float>(
                input_mem,
                static_cast<float*>(input.data),
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

#endif // USE_ONNXRUNTIME

} // namespace va::analyzer
