#include "analyzer/trt_session.hpp"
#include "core/logger.hpp"
#include "core/gpu_buffer_pool.hpp"
#include "core/buffer_pool.hpp"
#include "exec/stream_pool.hpp"

#include <algorithm>
#include <mutex>
#include <numeric>
#include <string>
#include <vector>

#if defined(USE_TENSORRT)
#include <cuda_runtime.h>
#include <NvInfer.h>
#include <NvOnnxParser.h>
// Ensure NV_TENSORRT_MAJOR is visible for feature guards
#if __has_include(<NvInferVersion.h>)
#include <NvInferVersion.h>
#endif
#endif

namespace va::analyzer {

namespace {
inline std::string shapeToStr(const std::vector<int64_t>& s){ std::string r; for(size_t i=0;i<s.size();++i){ r+=(i?"x":""); r+=std::to_string((long long)s[i]); } return r; }
}

struct TensorRTModelSession::Impl {
    Options options;
    std::mutex mutex;
    std::vector<std::string> output_names;
    std::unique_ptr<va::core::GpuBufferPool> device_pool;
    std::unique_ptr<va::core::HostBufferPool> host_pool;
    bool use_gpu {true};
    bool cpu_fallback {false};
    void* cuda_stream {nullptr};
#if defined(USE_TENSORRT)
    struct TRTLogger : public nvinfer1::ILogger {
        void log(Severity s, nvinfer1::AsciiChar const* msg) noexcept override {
            using L = ::va::core::LogLevel;
            L lvl = (s <= Severity::kWARNING) ? L::Warn : L::Debug;
            if (s == Severity::kERROR || s == Severity::kINTERNAL_ERROR) lvl = L::Error;
            VA_LOG_C(lvl, "analyzer.trt") << msg;
        }
    } logger;

    nvinfer1::IBuilder* builder {nullptr};
    nvinfer1::INetworkDefinition* network {nullptr};
    nvinfer1::IBuilderConfig* config {nullptr};
    nvonnxparser::IParser* parser {nullptr};
    nvinfer1::ICudaEngine* engine {nullptr};
    nvinfer1::IExecutionContext* context {nullptr};
    int nbBindings {0};
#endif
};

TensorRTModelSession::TensorRTModelSession() = default;
TensorRTModelSession::~TensorRTModelSession() {
#if defined(USE_TENSORRT)
    if (impl_) {
#if NV_TENSORRT_MAJOR < 10
        if (impl_->context) impl_->context->destroy();
        if (impl_->engine) impl_->engine->destroy();
        if (impl_->parser) impl_->parser->destroy();
        if (impl_->config) impl_->config->destroy();
        if (impl_->network) impl_->network->destroy();
        if (impl_->builder) impl_->builder->destroy();
#else
        // TensorRT 10+ uses updated lifetime management; avoid calling destroy()
        impl_->context = nullptr;
        impl_->engine = nullptr;
        impl_->parser = nullptr;
        impl_->config = nullptr;
        impl_->network = nullptr;
        impl_->builder = nullptr;
#endif
    }
#endif
}

void TensorRTModelSession::setOptions(const Options& opt) {
    if (!impl_) impl_ = std::make_unique<Impl>();
    std::scoped_lock lock(impl_->mutex);
    impl_->options = opt;
}

bool TensorRTModelSession::loadModel(const std::string& model_path, bool /*use_gpu*/) {
    if (!impl_) impl_ = std::make_unique<Impl>();
    std::scoped_lock lock(impl_->mutex);
    impl_->use_gpu = true;
    impl_->cuda_stream = impl_->options.user_stream ? impl_->options.user_stream : (void*)va::exec::StreamPool::instance().tls();

#if !defined(USE_TENSORRT)
    VA_LOG_ERROR() << "TensorRT native requested but not compiled (USE_TENSORRT off).";
    impl_->cpu_fallback = true;
    loaded_ = false;
    return false;
#else
#if NV_TENSORRT_MAJOR >= 10
    // Minimal stub for TensorRT 10+: native path not yet implemented; prefer ORT TensorRT EP
    VA_LOG_ERROR() << "TensorRT 10+ native path not implemented; please use ORT TensorRT EP (provider=tensorrt).";
    impl_->cpu_fallback = true;
    loaded_ = false;
    return false;
#else
    try {
        // Create builder/network/config
        impl_->builder = nvinfer1::createInferBuilder(impl_->logger);
        if (!impl_->builder) throw std::runtime_error("createInferBuilder failed");
        uint32_t flags = 1u << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
        impl_->network = impl_->builder->createNetworkV2(flags);
        if (!impl_->network) throw std::runtime_error("createNetworkV2 failed");
        impl_->config = impl_->builder->createBuilderConfig();
        if (!impl_->config) throw std::runtime_error("createBuilderConfig failed");
        impl_->parser = nvonnxparser::createParser(*impl_->network, impl_->logger);
        if (!impl_->parser) throw std::runtime_error("createParser failed");
        // Parse ONNX
        if (!impl_->parser->parseFromFile(model_path.c_str(), static_cast<int>(nvinfer1::ILogger::Severity::kWARNING))) {
            throw std::runtime_error("nvonnxparser parse failed");
        }
        // Config
        if (impl_->options.fp16) {
            impl_->config->setFlag(nvinfer1::BuilderFlag::kFP16);
        }
        const size_t workspace = impl_->options.workspace_mb > 0 ? static_cast<size_t>(impl_->options.workspace_mb) * 1024ull * 1024ull : 0ull;
#if NV_TENSORRT_MAJOR >= 8
        if (workspace > 0) {
            impl_->config->setMemoryPoolLimit(nvinfer1::MemoryPoolType::kWORKSPACE, workspace);
        }
#else
        if (workspace > 0) {
            impl_->config->setMaxWorkspaceSize(workspace);
        }
#endif
        // Build engine
        impl_->engine = impl_->builder->buildEngineWithConfig(*impl_->network, *impl_->config);
        if (!impl_->engine) throw std::runtime_error("buildEngineWithConfig failed");
        impl_->context = impl_->engine->createExecutionContext();
        if (!impl_->context) throw std::runtime_error("createExecutionContext failed");
        impl_->nbBindings = impl_->engine->getNbBindings();
        // Output names cache
        impl_->output_names.clear();
        for (int i = 0; i < impl_->nbBindings; ++i) {
            if (!impl_->engine->bindingIsInput(i)) {
                const char* nm = impl_->engine->getBindingName(i);
                if (nm) impl_->output_names.emplace_back(nm);
            }
        }
        // Device pool for outputs
        impl_->device_pool = std::make_unique<va::core::GpuBufferPool>(0 /*initial*/, 4);
        loaded_ = true;
        VA_LOG_C(::va::core::LogLevel::Info, "analyzer.trt") << "load: provider_req='tensorrt-native' resolved='tensorrt-native' outputs=" << impl_->output_names.size();
        return true;
    } catch (const std::exception& ex) {
        VA_LOG_ERROR() << "TensorRTModelSession load failed: " << ex.what();
        loaded_ = false;
        return false;
    }
#endif
#endif
}

bool TensorRTModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    outputs.clear();
    if (!loaded_ || !impl_) return false;
#if !defined(USE_TENSORRT)
    return false;
#else
#if NV_TENSORRT_MAJOR >= 10
    // TensorRT 10+ native path未实现：避免引用旧 API（bindingIsInput/getBindingDimensions/enqueueV2 等）
    VA_LOG_ERROR() << "TensorRT 10+ native path not implemented; please use ORT TensorRT EP (provider=tensorrt).";
    return false;
#else
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->context || !impl_->engine) return false;
    if (input.shape.empty() || input.dtype != core::DType::F32 || !input.data) return false;
    // Prepare bindings array
    const int nb = impl_->nbBindings;
    std::vector<void*> bindings(nb, nullptr);
    int inputIndex = -1;
    for (int i=0;i<nb;++i) if (impl_->engine->bindingIsInput(i)) { inputIndex = i; break; }
    if (inputIndex < 0) return false;

    // Set input dims (explicit batch)
    nvinfer1::Dims dims{}; dims.nbDims = static_cast<int>(input.shape.size());
    for (int i=0;i<dims.nbDims; ++i) dims.d[i] = static_cast<int>(input.shape[i]);
    if (!impl_->context->setBindingDimensions(inputIndex, dims)) {
        VA_LOG_ERROR() << "TensorRT setBindingDimensions failed, shape=" << shapeToStr(input.shape);
        return false;
    }

    // Prepare input device buffer
    const size_t elem_count = std::accumulate(input.shape.begin(), input.shape.end(), (size_t)1, std::multiplies<size_t>());
    const size_t bytes = elem_count * sizeof(float);
    void* in_dev = nullptr;
    va::core::GpuBufferPool::Memory pooled_in{};
    if (input.on_gpu) {
        in_dev = const_cast<void*>(static_cast<const void*>(input.data));
    } else {
        if (impl_->device_pool) {
            pooled_in = impl_->device_pool->acquire(bytes);
            in_dev = pooled_in.ptr;
        }
        if (!in_dev) {
            cudaError_t err = cudaMalloc(&in_dev, bytes);
            if (err != cudaSuccess) { VA_LOG_ERROR() << "cudaMalloc input failed"; return false; }
        }
        cudaError_t err = cudaMemcpyAsync(in_dev, input.data, bytes, cudaMemcpyHostToDevice,
                            impl_->cuda_stream ? reinterpret_cast<cudaStream_t>(impl_->cuda_stream) : 0);
        if (err != cudaSuccess) { VA_LOG_ERROR() << "H2D failed"; return false; }
    }
    bindings[inputIndex] = in_dev;

    // Allocate output buffers according to binding dims
    outputs.clear();
    for (int bi=0; bi<nb; ++bi) {
        if (impl_->engine->bindingIsInput(bi)) continue;
        auto bdims = impl_->context->getBindingDimensions(bi);
        size_t out_elem = 1; std::vector<int64_t> oshape; oshape.reserve(bdims.nbDims);
        for (int d=0; d<bdims.nbDims; ++d) { int v = bdims.d[d]; if (v<=0) v=1; oshape.push_back(v); out_elem *= static_cast<size_t>(v); }
        const size_t obytes = out_elem * sizeof(float);
        void* o_dev = nullptr;
        va::core::GpuBufferPool::Memory pooled_out{};
        if (impl_->device_pool) {
            pooled_out = impl_->device_pool->acquire(obytes);
            o_dev = pooled_out.ptr;
        }
        if (!o_dev) {
            if (cudaMalloc(&o_dev, obytes) != cudaSuccess) { VA_LOG_ERROR() << "cudaMalloc output failed"; return false; }
        }
        bindings[bi] = o_dev;
        core::TensorView tv; tv.data = o_dev; tv.on_gpu = true; tv.dtype = core::DType::F32; tv.shape = std::move(oshape);
        outputs.push_back(tv);
    }

    // Enqueue
    cudaStream_t stream = impl_->cuda_stream ? reinterpret_cast<cudaStream_t>(impl_->cuda_stream) : 0;
    bool ok = impl_->context->enqueueV2(bindings.data(), stream, nullptr);
    if (!ok) { VA_LOG_ERROR() << "TensorRT enqueueV2 failed"; return false; }
    // Outputs already reference device buffers; caller may stage to host downstream if需要
    return true;
#endif // NV_TENSORRT_MAJOR >= 10
#endif
}

IModelSession::ModelRuntimeInfo TensorRTModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info;
    info.provider = "tensorrt-native";
    info.gpu_active = true;
    info.device_binding = true;
    info.io_binding = false;
    info.cpu_fallback = impl_ ? impl_->cpu_fallback : false;
    return info;
}

std::vector<std::string> TensorRTModelSession::outputNames() const {
    if (!impl_) return {};
    std::scoped_lock lock(impl_->mutex);
    return impl_->output_names;
}

} // namespace va::analyzer
