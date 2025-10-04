#include "analyzer/ort_session.hpp"

#include "core/logger.hpp"
#include "core/buffer_pool.hpp"

#include <algorithm>
#include <cctype>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <mutex>
#include <numeric>
#include <string>
#include <utility>
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

inline core::DType mapElementType(ONNXTensorElementDataType type) {
    switch (type) {
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT:
        return core::DType::F32;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8:
        return core::DType::U8;
    case ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16:
        return core::DType::F16;
    default:
        VA_LOG_WARN() << "Unsupported tensor element type " << static_cast<int>(type)
                      << ", defaulting to F32";
        return core::DType::F32;
    }
}

inline constexpr std::size_t dtypeSize(core::DType dtype) {
    switch (dtype) {
    case core::DType::U8:
        return sizeof(std::uint8_t);
    case core::DType::F32:
        return sizeof(float);
    case core::DType::F16:
        return sizeof(std::uint16_t);
    default:
        return 0;
    }
}

inline ONNXTensorElementDataType toOrtElementType(core::DType dtype) {
    switch (dtype) {
    case core::DType::U8:
        return ONNX_TENSOR_ELEMENT_DATA_TYPE_UINT8;
    case core::DType::F32:
        return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT;
    case core::DType::F16:
        return ONNX_TENSOR_ELEMENT_DATA_TYPE_FLOAT16;
    default:
        return ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED;
    }
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
        VA_LOG_ERROR() << "cudaMalloc failed while allocating IoBinding buffer (" << required_bytes
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
    std::unique_ptr<Ort::Session> session_cpu; // CPU fallback session (lazy)
    std::unique_ptr<Ort::IoBinding> io_binding;
    std::vector<std::string> input_names_storage;
    std::vector<const char*> input_names;
    std::vector<std::string> output_names_storage;
    std::vector<const char*> output_names;
    std::vector<Ort::Value> last_outputs;
    std::vector<va::core::MemoryHandle> output_staging;
    std::shared_ptr<va::core::HostBufferPool> tensor_host_pool;
    std::shared_ptr<va::core::GpuBufferPool> tensor_device_pool;
    std::vector<std::shared_ptr<void>> output_device_owners;
    size_t host_pool_block_bytes {0};
    size_t device_pool_block_bytes {0};
    va::core::MemoryHandle input_staging_device;
    bool use_gpu {false};
    std::mutex mutex;
#if VA_HAS_CUDA_RUNTIME
    void* io_input_device_buffer {nullptr};
    size_t io_input_capacity_bytes {0};
#endif
    std::string resolved_provider {"cpu"};
    bool io_binding_enabled {false};
    bool device_binding_active {false};
    bool cpu_fallback {false};
    std::string model_path_str; // keep original model path for CPU fallback session
};

OrtModelSession::OrtModelSession() = default;
OrtModelSession::~OrtModelSession() {
#if VA_HAS_CUDA_RUNTIME
    if (impl_) {
        std::scoped_lock lock(impl_->mutex);
        releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
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
        impl_->model_path_str = model_path;
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

    impl_->output_staging.clear();
    if (impl_->options.stage_device_outputs) {
        impl_->output_staging.reserve(output_count);
    }

    impl_->resolved_provider = provider_appended ? provider : std::string{"cpu"};
    impl_->cpu_fallback = gpu_requested && !provider_appended;

    if (impl_->options.use_io_binding && impl_->use_gpu) {
        try {
            impl_->io_binding = std::make_unique<Ort::IoBinding>(*impl_->session);
            VA_LOG_INFO() << "OrtModelSession IoBinding enabled (provider="
                          << (provider_appended ? provider : "cpu")
                          << ")";
#if VA_HAS_CUDA_RUNTIME
            if (impl_->options.io_binding_input_bytes > 0) {
                ensureCudaCapacity(impl_->io_input_device_buffer,
                                   impl_->io_input_capacity_bytes,
                                   impl_->options.io_binding_input_bytes);
            } else {
                releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
            }
#endif
            impl_->io_binding_enabled = true;
        } catch (const std::exception& ex) {
            VA_LOG_WARN() << "Failed to initialize IoBinding: " << ex.what();
            impl_->io_binding.reset();
#if VA_HAS_CUDA_RUNTIME
            releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
#endif
            impl_->io_binding_enabled = false;
            impl_->device_binding_active = false;
        }
    } else {
        impl_->io_binding.reset();
#if VA_HAS_CUDA_RUNTIME
        releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
#endif
        impl_->io_binding_enabled = false;
        impl_->device_binding_active = false;
    }

    impl_->device_binding_active = impl_->use_gpu;

    loaded_ = true;
    return true;
}

namespace {
core::TensorView makeTensorView(Ort::Value& value,
                                va::core::MemoryHandle* host_stage_handle,
                                bool* wrote_gpu_flag) {
    core::TensorView view;
    if (!value.IsTensor()) {
        return view;
    }

    Ort::TensorTypeAndShapeInfo shape_info = value.GetTensorTypeAndShapeInfo();
    view.shape = shape_info.GetShape();
    view.dtype = mapElementType(shape_info.GetElementType());

    const std::size_t element_size = dtypeSize(view.dtype);
    if (element_size == 0) {
        VA_LOG_ERROR() << "Unsupported tensor element size for dtype.";
        return view;
    }

    const std::size_t element_count = shape_info.GetElementCount();
    if (element_count > 0 && element_count > (std::numeric_limits<std::size_t>::max() / element_size)) {
        VA_LOG_ERROR() << "Tensor element count overflow while computing buffer size.";
        return view;
    }

    view.bytes = element_count * element_size;

    Ort::ConstMemoryInfo mem_info = value.GetTensorMemoryInfo();
    const bool is_gpu = mem_info.GetDeviceType() == OrtMemoryInfoDeviceType_GPU;
    if (wrote_gpu_flag) {
        *wrote_gpu_flag = is_gpu;
    }

    const void* raw_data = value.GetTensorRawData();

    if (!is_gpu) {
        view.data = const_cast<void*>(raw_data);
        view.device_data = nullptr;
        view.on_gpu = false;
        (void)host_stage_handle;
        view.handle.host_ptr = view.data;
        view.handle.device_ptr = nullptr;
        view.handle.bytes = view.bytes;
        view.handle.pitch = 0;
        view.handle.width = 0;
        view.handle.height = 0;
        view.handle.stream = nullptr;
        view.handle.location = core::MemoryLocation::Host;
        view.handle.format = core::PixelFormat::Unknown;
        return view;
    }

// will be replaced with pool usage later

#if VA_HAS_CUDA_RUNTIME
    view.device_data = const_cast<void*>(raw_data);
    view.on_gpu = true;
    if (!raw_data || view.bytes == 0) {
        view.data = nullptr;
        if (host_stage_handle) { *host_stage_handle = {}; }
        return view;
    }
    if (host_stage_handle && host_stage_handle->host_ptr) {
        // 假定上层已经通过池分配了足够容量
        cudaError_t err = cudaMemcpy(host_stage_handle->host_ptr, raw_data, view.bytes, cudaMemcpyDeviceToHost);
        if (err != cudaSuccess) {
            VA_LOG_ERROR() << "cudaMemcpy device->host failed for IoBinding output: " << cudaGetErrorString(err);
            *host_stage_handle = {};
            view.data = nullptr;
        } else {
            host_stage_handle->bytes = view.bytes;
            view.data = host_stage_handle->host_ptr;
        }
    } else {
        view.data = nullptr;
    }
    view.handle.host_ptr = view.data;
    view.handle.device_ptr = view.device_data;
    view.handle.bytes = view.bytes;
    view.handle.pitch = 0;
    view.handle.width = 0;
    view.handle.height = 0;
    view.handle.stream = nullptr;
    view.handle.location = core::MemoryLocation::Device;
    view.handle.format = core::PixelFormat::Unknown;
#else
    (void)host_stage_handle;
    view.device_data = const_cast<void*>(raw_data);
    view.on_gpu = true;
    view.data = nullptr;
    VA_LOG_WARN() << "GPU tensor produced but CUDA runtime support not compiled.";
    view.handle.host_ptr = nullptr;
    view.handle.device_ptr = view.device_data;
    view.handle.bytes = view.bytes;
    view.handle.pitch = 0;
    view.handle.width = 0;
    view.handle.height = 0;
    view.handle.stream = nullptr;
    view.handle.location = core::MemoryLocation::Device;
    view.handle.format = core::PixelFormat::Unknown;
#endif
    return view;
}
}

bool OrtModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    if (!loaded_ || !impl_ || !impl_->session) {
        return false;
    }

    const bool has_host_input = input.data != nullptr;
    const bool has_device_input = input.device_data != nullptr;
    if ((!has_host_input && !has_device_input) || input.shape.empty()) {
        return false;
    }

    std::scoped_lock lock(impl_->mutex);

    const std::size_t element_count = std::accumulate(input.shape.begin(), input.shape.end(), static_cast<std::size_t>(1), std::multiplies<std::size_t>());
    if (element_count == 0) {
        return false;
    }

    const std::size_t element_size = dtypeSize(input.dtype);
    if (element_size == 0) {
        VA_LOG_ERROR() << "Unsupported tensor dtype for inference input.";
        return false;
    }

    if (element_count > 0 && element_count > (std::numeric_limits<std::size_t>::max() / element_size)) {
        VA_LOG_ERROR() << "Tensor element count overflow while preparing inference input.";
        return false;
    }

    const std::size_t required_bytes = element_count * element_size;
    const auto ort_input_type = toOrtElementType(input.dtype);
    if (ort_input_type == ONNX_TENSOR_ELEMENT_DATA_TYPE_UNDEFINED) {
        VA_LOG_ERROR() << "Unable to convert tensor dtype to ONNX element type.";
        return false;
    }

    try {
        bool device_binding_active = false;

        if (impl_->io_binding) {
            impl_->io_binding->ClearBoundInputs();
            impl_->io_binding->ClearBoundOutputs();

            std::vector<Ort::Value> input_holders;
            input_holders.reserve(1);

            bool bound_device_input = false;
#if VA_HAS_CUDA_RUNTIME
            if (impl_->options.use_io_binding && impl_->use_gpu) {
                if (input.on_gpu && has_device_input) {
                    Ort::MemoryInfo input_mem("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                    input_holders.emplace_back(Ort::Value::CreateTensor(input_mem,
                                                                        input.device_data,
                                                                        required_bytes,
                                                                        const_cast<int64_t*>(input.shape.data()),
                                                                        input.shape.size(),
                                                                        ort_input_type));
                    bound_device_input = true;
                } else {
                    // 当偏好 pinned 内存时，不进行手动 H2D 设备 staging，改为绑定 CudaPinned 由 ORT 完成拷贝
                    if (!impl_->options.prefer_pinned_memory) {
                        // 优先使用设备侧缓冲池进行输入 staging
                        std::size_t target_bytes = std::max(required_bytes, impl_->options.io_binding_input_bytes);
                        std::unique_ptr<va::core::MemoryHandle> staging_handle;
                        if (impl_->options.tensor_device_pool_bytes > 0) {
                            std::size_t pool_block = std::max(impl_->options.tensor_device_pool_bytes, target_bytes);
                            if (!impl_->tensor_device_pool || impl_->device_pool_block_bytes < pool_block) {
                                impl_->tensor_device_pool = std::make_shared<va::core::GpuBufferPool>(pool_block, 8);
                                impl_->device_pool_block_bytes = pool_block;
                            }
                            auto handle = impl_->tensor_device_pool->acquire();
                            if (handle.device_ptr && handle.bytes >= target_bytes) {
                                staging_handle = std::make_unique<va::core::MemoryHandle>(std::move(handle));
                            }
                        }
                        // 如果设备池不可用，退回到单一 cudaMalloc 缓冲（旧逻辑）
                        if (!staging_handle) {
                            if (target_bytes > 0 && !impl_->io_input_device_buffer) {
                                ensureCudaCapacity(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes, target_bytes);
                            } else if (target_bytes > 0 && impl_->io_input_capacity_bytes < target_bytes) {
                                if (!ensureCudaCapacity(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes, target_bytes)) {
                                    target_bytes = 0;
                                }
                            }
                        }

                        if ((staging_handle || impl_->io_input_device_buffer) && target_bytes > 0 && has_host_input) {
                            void* dst = staging_handle ? staging_handle->device_ptr : impl_->io_input_device_buffer;
                            cudaError_t copy_err = cudaMemcpy(dst,
                                                              input.data,
                                                              required_bytes,
                                                              cudaMemcpyHostToDevice);
                            if (copy_err != cudaSuccess) {
                                VA_LOG_ERROR() << "cudaMemcpy host->device failed for IoBinding input: "
                                               << cudaGetErrorString(copy_err);
                                if (staging_handle) {
                                    // 归还失败的句柄
                                    impl_->tensor_device_pool->release(std::move(*staging_handle));
                                    staging_handle.reset();
                                } else {
                                    releaseCudaBuffer(impl_->io_input_device_buffer, impl_->io_input_capacity_bytes);
                                }
                            } else {
                                Ort::MemoryInfo input_mem("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                                void* dev_ptr = staging_handle ? staging_handle->device_ptr : impl_->io_input_device_buffer;
                                input_holders.emplace_back(Ort::Value::CreateTensor(input_mem,
                                                                                    dev_ptr,
                                                                                    required_bytes,
                                                                                    const_cast<int64_t*>(input.shape.data()),
                                                                                    input.shape.size(),
                                                                                    ort_input_type));
                                bound_device_input = true;
                                if (staging_handle) {
                                    // 保存句柄以便 Run 完成后归还到池
                                    impl_->input_staging_device = std::move(*staging_handle);
                                    staging_handle.reset();
                                }
                            }
                        }
                        // 推理完成后在下方清理/归还 staging_handle（见 outputs 构建后）
                    }
                }
            }
#endif

            if (!bound_device_input) {
                if (!has_host_input) {
                    VA_LOG_ERROR() << "Input tensor lacks host pointer required for CPU binding.";
                    return false;
                }

                Ort::MemoryInfo input_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                if (impl_->options.use_io_binding && impl_->use_gpu && impl_->options.prefer_pinned_memory) {
                    input_mem = Ort::MemoryInfo("CudaPinned", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeCPU);
                }

                input_holders.emplace_back(Ort::Value::CreateTensor(input_mem,
                                                                    input.data,
                                                                    required_bytes,
                                                                    const_cast<int64_t*>(input.shape.data()),
                                                                    input.shape.size(),
                                                                    ort_input_type));
            }

            const char* input_name = impl_->input_names.empty() ? "input" : impl_->input_names.front();
            impl_->io_binding->BindInput(input_name, input_holders.front());

            for (const char* output_name : impl_->output_names) {
                if (impl_->options.use_io_binding && impl_->use_gpu) {
                    Ort::MemoryInfo out_mem("Cuda", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeDefault);
                    impl_->io_binding->BindOutput(output_name, out_mem);
                } else {
                    Ort::MemoryInfo out_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                    if (impl_->options.use_io_binding && impl_->use_gpu && impl_->options.prefer_pinned_memory) {
                        out_mem = Ort::MemoryInfo("CudaPinned", OrtDeviceAllocator, impl_->options.device_id, OrtMemTypeCPUOutput);
                    }
                    impl_->io_binding->BindOutput(output_name, out_mem);
                }
            }

            Ort::RunOptions run_opts;
            impl_->session->Run(run_opts, *impl_->io_binding);
            impl_->io_binding->SynchronizeOutputs();

            impl_->last_outputs = impl_->io_binding->GetOutputValues();
            // 释放上一轮 staging 句柄以便复用
            if (!impl_->output_staging.empty() && impl_->tensor_host_pool) {
                for (auto& h : impl_->output_staging) {
                    if (h.host_ptr) {
                        impl_->tensor_host_pool->release(std::move(h));
                    }
                }
                impl_->output_staging.clear();
            } else {
                impl_->output_staging.clear();
            }
            if (impl_->options.stage_device_outputs) {
                impl_->output_staging.resize(impl_->last_outputs.size());
            }

            outputs.clear();
            outputs.reserve(impl_->last_outputs.size());

            bool observed_gpu_output = false;
            for (std::size_t idx = 0; idx < impl_->last_outputs.size(); ++idx) {
                bool tensor_on_gpu = false;
                va::core::MemoryHandle* stage_handle = nullptr;
                if (impl_->options.stage_device_outputs && idx < impl_->output_staging.size()) {
                    // 先读取本次输出的 shape 来计算所需字节
                    Ort::TensorTypeAndShapeInfo shape_info = impl_->last_outputs[idx].GetTensorTypeAndShapeInfo();
                    const auto dtype = mapElementType(shape_info.GetElementType());
                    const std::size_t esize = dtypeSize(dtype);
                    std::size_t ecount = shape_info.GetElementCount();
                    if (esize == 0 || (ecount > 0 && ecount > (std::numeric_limits<std::size_t>::max() / esize))) {
                        ecount = 0;
                    }
                    std::size_t required = ecount * esize;
                    std::size_t target_bytes = std::max(required, impl_->options.tensor_host_pool_bytes);
                    if (target_bytes == 0) target_bytes = 1; // 至少申请 1 字节
                    if (!impl_->tensor_host_pool || impl_->host_pool_block_bytes < target_bytes) {
                        impl_->tensor_host_pool = std::make_shared<va::core::HostBufferPool>(target_bytes, 8, impl_->options.prefer_pinned_memory);
                        impl_->host_pool_block_bytes = target_bytes;
                    }
                    auto handle = impl_->tensor_host_pool->acquire();
                    if (handle.host_ptr && handle.bytes >= target_bytes) {
                        impl_->output_staging[idx] = std::move(handle);
                        stage_handle = &impl_->output_staging[idx];
                    } else {
                        // 申请失败则不做 staging，由下游根据需要 ensureHost()
                        if (handle.host_ptr) {
                            impl_->tensor_host_pool->release(std::move(handle));
                        }
                    }
                }
                auto tensor = makeTensorView(impl_->last_outputs[idx], stage_handle, &tensor_on_gpu);
                if (tensor_on_gpu && impl_->options.stage_device_outputs && stage_handle && !tensor.data) {
                    VA_LOG_ERROR() << "Failed to stage GPU output buffer for host access.";
                    return false;
                }
                outputs.push_back(std::move(tensor));
                observed_gpu_output = observed_gpu_output || tensor_on_gpu;
            }

            impl_->io_binding->ClearBoundInputs();
            impl_->io_binding->ClearBoundOutputs();

            device_binding_active = impl_->use_gpu && (bound_device_input || observed_gpu_output);

            // 归还可能占用的输入 staging 设备缓冲
            // 注意：如果使用了单一 cudaMalloc 的 io_input_device_buffer 则保留以便复用
            // 使用池分配的 input_staging_device 在此归还到池
#if VA_HAS_CUDA_RUNTIME
            if (impl_->tensor_device_pool && impl_->input_staging_device.device_ptr) {
                impl_->tensor_device_pool->release(std::move(impl_->input_staging_device));
            }
#endif
                } else {
            if (!has_host_input) {
                VA_LOG_ERROR() << "Input tensor requires CPU data when IoBinding is disabled.";
                return false;
            }

            Ort::MemoryInfo input_mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
            Ort::Value input_tensor = Ort::Value::CreateTensor(input_mem,
                                                               input.data,
                                                               required_bytes,
                                                               const_cast<int64_t*>(input.shape.data()),
                                                               input.shape.size(),
                                                               ort_input_type);

            impl_->last_outputs = impl_->session->Run(Ort::RunOptions{nullptr},
                                                       impl_->input_names.data(),
                                                       &input_tensor,
                                                       1,
                                                       impl_->output_names.data(),
                                                       impl_->output_names.size());
            impl_->output_staging.clear();

            // 释放上一轮 staging（若存在）
            if (!impl_->output_staging.empty() && impl_->tensor_host_pool) {
                for (auto& h : impl_->output_staging) {
                    if (h.host_ptr) {
                        impl_->tensor_host_pool->release(std::move(h));
                    }
                }
                impl_->output_staging.clear();
            }
            outputs.clear();
            outputs.reserve(impl_->last_outputs.size());
            for (auto& value : impl_->last_outputs) {
                outputs.push_back(makeTensorView(value, nullptr, nullptr));
            }

            device_binding_active = false;
        }

        impl_->device_binding_active = device_binding_active;

        OrtModelSession::RuntimeInfo runtime_snapshot;
        runtime_snapshot.provider = impl_->resolved_provider;
        runtime_snapshot.gpu_active = impl_->use_gpu;
        runtime_snapshot.io_binding_active = impl_->io_binding_enabled && impl_->io_binding != nullptr;
        runtime_snapshot.device_binding_active = impl_->device_binding_active;
        runtime_snapshot.cpu_fallback = impl_->cpu_fallback;
        if (impl_->options.runtime_callback) {
            impl_->options.runtime_callback(runtime_snapshot);
        }
    } catch (const Ort::Exception& ex) {
        VA_LOG_ERROR() << "OrtModelSession inference failed: " << ex.what();
        if (impl_->options.allow_cpu_fallback) {
            try {
                if (!impl_->session_cpu && !impl_->model_path_str.empty()) {
                    Ort::SessionOptions so;
                    so.SetIntraOpNumThreads(1);
                    so.SetGraphOptimizationLevel(GraphOptimizationLevel::ORT_ENABLE_ALL);
#ifdef _WIN32
                    std::wstring wpath(impl_->model_path_str.begin(), impl_->model_path_str.end());
                    impl_->session_cpu = std::make_unique<Ort::Session>(*impl_->env, wpath.c_str(), so);
#else
                    impl_->session_cpu = std::make_unique<Ort::Session>(*impl_->env, impl_->model_path_str.c_str(), so);
#endif
                }
                if (impl_->session_cpu) {
                    // Build CPU input tensor
                    std::vector<uint8_t> host_stage;
                    const void* host_ptr = input.data;
                    if (!host_ptr && input.device_data && input.bytes > 0) {
#if VA_HAS_CUDA_RUNTIME
                        host_stage.resize(input.bytes);
                        cudaMemcpy(host_stage.data(), input.device_data, input.bytes, cudaMemcpyDeviceToHost);
                        host_ptr = host_stage.data();
#else
                        host_ptr = nullptr;
#endif
                    }
                    if (!host_ptr) {
                        return false;
                    }
                    Ort::MemoryInfo mem = Ort::MemoryInfo::CreateCpu(OrtArenaAllocator, OrtMemTypeDefault);
                    Ort::Value input_tensor = Ort::Value::CreateTensor(mem,
                                                                       const_cast<void*>(host_ptr),
                                                                       required_bytes,
                                                                       const_cast<int64_t*>(input.shape.data()),
                                                                       input.shape.size(),
                                                                       toOrtElementType(input.dtype));
                    impl_->last_outputs = impl_->session_cpu->Run(Ort::RunOptions{nullptr},
                                                                  impl_->input_names.data(),
                                                                  &input_tensor,
                                                                  1,
                                                                  impl_->output_names.data(),
                                                                  impl_->output_names.size());
                    outputs.clear();
                    outputs.reserve(impl_->last_outputs.size());
                    for (auto& value : impl_->last_outputs) {
                        outputs.push_back(makeTensorView(value, nullptr, nullptr));
                    }
                    impl_->device_binding_active = false;
                    impl_->cpu_fallback = true;

                    OrtModelSession::RuntimeInfo runtime_snapshot;
                    runtime_snapshot.provider = impl_->resolved_provider;
                    runtime_snapshot.gpu_active = false;
                    runtime_snapshot.io_binding_active = false;
                    runtime_snapshot.device_binding_active = false;
                    runtime_snapshot.cpu_fallback = true;
                    if (impl_->options.runtime_callback) {
                        impl_->options.runtime_callback(runtime_snapshot);
                    }
                    return true;
                }
            } catch (const Ort::Exception& ex2) {
                VA_LOG_ERROR() << "CPU fallback failed: " << ex2.what();
            } catch (const std::exception& ex2) {
                VA_LOG_ERROR() << "CPU fallback failed: " << ex2.what();
            }
        }
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

#endif // USE_ONNXRUNTIME

} // namespace va::analyzer
