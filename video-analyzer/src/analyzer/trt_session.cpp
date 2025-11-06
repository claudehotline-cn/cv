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
#include <fstream>
#include <sstream>
#include <filesystem>

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
    // Staged device buffers to keep outputs alive across pipeline stages for the
    // previous run. We release/recycle them at the beginning of the next run.
    std::vector<va::core::GpuBufferPool::Memory> staged_outputs;
    std::vector<void*> staged_raw_cuda; // non-pooled fallbacks allocated via cudaMalloc
    // Staged input buffers (when we H2D stage for CPU input)
    std::vector<va::core::GpuBufferPool::Memory> staged_inputs;
    std::vector<void*> staged_input_raw;
    bool use_gpu {true};
    bool cpu_fallback {false};
    void* cuda_stream {nullptr};
#if defined(USE_TENSORRT)
    struct TRTLogger : public nvinfer1::ILogger {
        // Throttle INFO/VERBOSE logs to avoid flooding. Immediate for WARN/ERROR.
        int throttle_ms {1000};
        std::atomic<unsigned long long> suppressed {0};
        std::atomic<long long> last_emit_ms {0};
        TRTLogger() {
            if (const char* e = std::getenv("VA_TRT_LOG_THROTTLE_MS")) {
                try { int v = std::stoi(e); if (v >= 0) throttle_ms = v; } catch (...) {}
            }
        }
        static long long now_ms() {
            using namespace std::chrono; return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count();
        }
        void log(Severity s, nvinfer1::AsciiChar const* msg) noexcept override {
            using L = ::va::core::LogLevel;
            // Map TRT severity to our levels
            if (s == Severity::kERROR || s == Severity::kINTERNAL_ERROR) {
                VA_LOG_C(L::Error, "analyzer.trt") << msg;
                return;
            }
            if (s == Severity::kWARNING) {
                VA_LOG_C(L::Warn, "analyzer.trt") << msg;
                return;
            }
            // INFO/VERBOSE: throttle output
            if (throttle_ms <= 0) { VA_LOG_C(L::Debug, "analyzer.trt") << msg; return; }
            const long long now = now_ms();
            long long last = last_emit_ms.load(std::memory_order_relaxed);
            if (now - last >= throttle_ms && last_emit_ms.compare_exchange_strong(last, now)) {
                unsigned long long sup = suppressed.exchange(0, std::memory_order_relaxed);
                if (sup > 0) {
                    VA_LOG_C(L::Debug, "analyzer.trt") << "[throttled] suppressed " << sup << " messages";
                }
                VA_LOG_C(L::Debug, "analyzer.trt") << msg;
            } else {
                suppressed.fetch_add(1, std::memory_order_relaxed);
            }
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
    try {
        // If model_path points to a serialized TensorRT engine (.engine/.plan), load it directly.
        {
            std::string lower = model_path; std::transform(lower.begin(), lower.end(), lower.begin(), [](unsigned char c){ return (char)std::tolower(c); });
            const bool is_plan = (lower.size()>=7 && (lower.rfind(".engine") == lower.size()-7 || lower.rfind(".plan") == lower.size()-5));
            if (is_plan) {
                std::ifstream ifs(model_path, std::ios::binary);
                if (!ifs.good()) throw std::runtime_error("engine file not found");
                std::vector<char> buf((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
                auto* runtime = nvinfer1::createInferRuntime(impl_->logger);
                if (!runtime) throw std::runtime_error("createInferRuntime failed");
                impl_->engine = runtime->deserializeCudaEngine(buf.data(), buf.size());
                if (!impl_->engine) throw std::runtime_error("deserializeCudaEngine failed");
                impl_->context = impl_->engine->createExecutionContext();
                if (!impl_->context) throw std::runtime_error("createExecutionContext failed");
                // Collect output tensor names
                impl_->output_names.clear();
                int numIO = impl_->engine->getNbIOTensors();
                for (int i = 0; i < numIO; ++i) {
                    const char* nm = impl_->engine->getIOTensorName(i);
                    if (!nm) continue;
                    if (impl_->engine->getTensorIOMode(nm) == nvinfer1::TensorIOMode::kOUTPUT) {
                        impl_->output_names.emplace_back(nm);
                    }
                }
                impl_->device_pool = std::make_unique<va::core::GpuBufferPool>(0, 4);
                loaded_ = true;
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.trt") << "load: provider_req='tensorrt-native' resolved='tensorrt-native' (engine) outputs=" << impl_->output_names.size();
                return true;
            }
        }
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
        if (workspace > 0) {
            impl_->config->setMemoryPoolLimit(nvinfer1::MemoryPoolType::kWORKSPACE, workspace);
        }
        // Basic builder tuning (env overrides)
        auto get_env_int = [](const char* k, int defv){ if (const char* e = std::getenv(k)) { try { return std::stoi(e); } catch (...) {} } return defv; };
        int opt = get_env_int("VA_TRT_BUILDER_OPT", impl_->options.builder_opt_level);
        try { impl_->config->setBuilderOptimizationLevel(opt); } catch (...) {}
        int minIter = get_env_int("VA_TRT_MIN_TIMING", impl_->options.min_timing_iterations);
        int avgIter = get_env_int("VA_TRT_AVG_TIMING", impl_->options.avg_timing_iterations);
#if NV_TENSORRT_MAJOR < 10
        try { impl_->config->setMinTimingIterations(minIter); } catch (...) {}
        try { impl_->config->setAvgTimingIterations(avgIter); } catch (...) {}
#else
        // In TRT 10, setMinTimingIterations may be removed; keep avg iterations if available.
        try { impl_->config->setAvgTimingIterations(avgIter); } catch (...) {}
#endif
        // Restrict tactic sources if requested
        if (const char* ts = std::getenv("VA_TRT_TACTIC_SOURCES")) {
            std::string v = ts; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);});
            uint64_t mask = 0;
#ifdef NV_TENSORRT_MAJOR
            if (v.find("cublaslt") != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS_LT));
            if (v.find("cublas") != std::string::npos)   mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS));
            if (v.find("cudnn") != std::string::npos)    mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUDNN));
            if (mask) { try { impl_->config->setTacticSources(mask); } catch (...) {} }
#endif
        }
        // Reduce tactic spew: lower profiling verbosity unless explicitly enabled
        try {
            bool verbose = false;
            if (const char* e = std::getenv("VA_TRT_VERBOSE_TACTICS")) {
                std::string v = e; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);});
                verbose = (v=="1"||v=="true"||v=="yes");
            }
            impl_->config->setProfilingVerbosity(verbose ? nvinfer1::ProfilingVerbosity::kDETAILED : nvinfer1::ProfilingVerbosity::kNONE);
        } catch (...) { /* ignore if not supported */ }

        // Timing cache load (native TRT):
        try {
            std::string cache_dir = "/app/.trt_native_cache";
            if (const char* e = std::getenv("VA_TRT_CACHE_DIR")) cache_dir = e;
            std::error_code ec; std::filesystem::create_directories(cache_dir, ec);
            std::string cache_path = cache_dir + "/timing_sm";
            // Append arch if available
            try {
                int dev=0; cudaDeviceProp prop{}; cudaGetDevice(&dev); if (cudaGetDeviceProperties(&prop, dev)==cudaSuccess) {
                    std::ostringstream oss; oss << cache_path << (int)prop.major << (int)prop.minor << ".blob"; cache_path = oss.str();
                }
            } catch (...) {}
            std::ifstream ifs(cache_path, std::ios::binary);
            if (ifs.good()) {
                std::vector<char> buf((std::istreambuf_iterator<char>(ifs)), std::istreambuf_iterator<char>());
                if (!buf.empty()) {
                    auto* tc = impl_->config->createTimingCache(buf.data(), buf.size());
                    if (tc) { impl_->config->setTimingCache(*tc, false); VA_LOG_C(::va::core::LogLevel::Info, "analyzer.trt") << "TRT native: loaded timing cache from '" << cache_path << "'"; }
                }
            }
            // After build, we will serialize timing cache again
        } catch (...) {}
        // Optimization profile for dynamic shapes (minimal 1x3x640x640 fallback)
        try {
            nvinfer1::IOptimizationProfile* prof = impl_->builder->createOptimizationProfile();
            const char* inName = nullptr;
            // Try get first input tensor name from network
            int nbInputs = 0;
            try { nbInputs = impl_->network->getNbInputs(); } catch (...) { nbInputs = 0; }
            if (nbInputs > 0) {
                try {
                    auto* in = impl_->network->getInput(0);
                    if (in) inName = in->getName();
                } catch (...) { inName = nullptr; }
            }
            if (!inName) {
                // Heuristic common names
                static const char* guesses[] = {"images", "input", "data", "input_0", "inputs"};
                for (auto g : guesses) { inName = g; break; }
            }
            if (prof && inName) {
                nvinfer1::Dims minD{4, {1,3,640,640}};
                nvinfer1::Dims optD{4, {1,3,640,640}};
                nvinfer1::Dims maxD{4, {1,3,640,640}};
                bool ok = prof->setDimensions(inName, nvinfer1::OptProfileSelector::kMIN, minD)
                       && prof->setDimensions(inName, nvinfer1::OptProfileSelector::kOPT, optD)
                       && prof->setDimensions(inName, nvinfer1::OptProfileSelector::kMAX, maxD);
                if (ok) {
                    impl_->config->addOptimizationProfile(prof);
                    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.trt")
                        << "TRT native: added optimization profile for '" << inName << "' min/opt/max=1x3x640x640";
                } else {
                    VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.trt") << "TRT native: set profile dims failed for input '" << inName << "'";
                }
            } else {
                VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.trt") << "TRT native: no input name found to create optimization profile";
            }
        } catch (const std::exception& ex) {
            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.trt") << "TRT native: optimization profile setup skipped: " << ex.what();
        } catch (...) {
            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.trt") << "TRT native: optimization profile setup skipped (unknown error)";
        }
        // Build engine
        impl_->engine = impl_->builder->buildEngineWithConfig(*impl_->network, *impl_->config);
        if (!impl_->engine) throw std::runtime_error("buildEngineWithConfig failed");
        // Save timing cache for next runs
        try {
            auto* tc = impl_->config->getTimingCache();
            if (tc) {
                nvinfer1::IHostMemory* mem = tc->serialize();
                if (mem && mem->size() > 0) {
                    std::string cache_dir = "/app/.trt_native_cache";
                    if (const char* e = std::getenv("VA_TRT_CACHE_DIR")) cache_dir = e;
                    std::error_code ec; std::filesystem::create_directories(cache_dir, ec);
                    std::string cache_path = cache_dir + "/timing_sm";
                    try {
                        int dev=0; cudaDeviceProp prop{}; cudaGetDevice(&dev); if (cudaGetDeviceProperties(&prop, dev)==cudaSuccess) {
                            std::ostringstream oss; oss << cache_path << (int)prop.major << (int)prop.minor << ".blob"; cache_path = oss.str();
                        }
                    } catch (...) {}
                    std::ofstream ofs(cache_path, std::ios::binary);
                    ofs.write(static_cast<const char*>(mem->data()), mem->size());
                    ofs.close();
                    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.trt") << "TRT native: saved timing cache to '" << cache_path << "' size=" << mem->size();
#if NV_TENSORRT_MAJOR < 10
                    mem->destroy();
#endif
                }
            }
        } catch (...) {}
        impl_->context = impl_->engine->createExecutionContext();
        if (!impl_->context) throw std::runtime_error("createExecutionContext failed");
        // Cache tensor names (outputs)
        impl_->output_names.clear();
        int numIO = impl_->engine->getNbIOTensors();
        for (int i = 0; i < numIO; ++i) {
            const char* nm = impl_->engine->getIOTensorName(i);
            if (!nm) continue;
            if (impl_->engine->getTensorIOMode(nm) == nvinfer1::TensorIOMode::kOUTPUT) {
                impl_->output_names.emplace_back(nm);
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
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->context || !impl_->engine) return false;
    if (input.shape.empty() || input.dtype != core::DType::F32 || !input.data) return false;
    // Recycle staged buffers from previous run (safe on same stream order)
    if (impl_->device_pool && !impl_->staged_outputs.empty()) {
        for (auto &m : impl_->staged_outputs) impl_->device_pool->release(std::move(m));
        impl_->staged_outputs.clear();
    }
    for (void* p : impl_->staged_raw_cuda) { if (p) cudaFree(p); }
    impl_->staged_raw_cuda.clear();
    if (impl_->device_pool && !impl_->staged_inputs.empty()) {
        for (auto &m : impl_->staged_inputs) impl_->device_pool->release(std::move(m));
        impl_->staged_inputs.clear();
    }
    for (void* p : impl_->staged_input_raw) { if (p) cudaFree(p); }
    impl_->staged_input_raw.clear();
    // Find first input tensor name
    int numIO = impl_->engine->getNbIOTensors();
    const char* inputName = nullptr;
    for (int i = 0; i < numIO; ++i) {
        const char* nm = impl_->engine->getIOTensorName(i);
        if (nm && impl_->engine->getTensorIOMode(nm) == nvinfer1::TensorIOMode::kINPUT) { inputName = nm; break; }
    }
    if (!inputName) return false;
    // Set input shape
    nvinfer1::Dims dims{}; dims.nbDims = static_cast<int>(input.shape.size());
    for (int i=0;i<dims.nbDims && i<8; ++i) dims.d[i] = static_cast<int>(input.shape[i]);
    if (!impl_->context->setInputShape(inputName, dims)) {
        VA_LOG_ERROR() << "TensorRT setInputShape failed, shape=" << shapeToStr(input.shape);
        return false;
    }
    // Prepare input buffer
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
            impl_->staged_input_raw.push_back(in_dev);
        }
        cudaError_t err = cudaMemcpyAsync(in_dev, input.data, bytes, cudaMemcpyHostToDevice,
                            impl_->cuda_stream ? reinterpret_cast<cudaStream_t>(impl_->cuda_stream) : 0);
        if (err != cudaSuccess) { VA_LOG_ERROR() << "H2D failed"; return false; }
        if (pooled_in.ptr) {
            impl_->staged_inputs.emplace_back(std::move(pooled_in));
        }
    }
    // Bind input tensor address
    if (!impl_->context->setTensorAddress(inputName, in_dev)) {
        VA_LOG_ERROR() << "setTensorAddress(input) failed";
        return false;
    }
    // Allocate and bind outputs
    outputs.clear();
    for (int i = 0; i < numIO; ++i) {
        const char* nm = impl_->engine->getIOTensorName(i);
        if (!nm) continue;
        if (impl_->engine->getTensorIOMode(nm) != nvinfer1::TensorIOMode::kOUTPUT) continue;
        nvinfer1::Dims odims = impl_->context->getTensorShape(nm);
        size_t out_elem = 1; std::vector<int64_t> oshape; oshape.reserve(odims.nbDims);
        for (int d=0; d<odims.nbDims; ++d) { int v = odims.d[d]; if (v<=0) v=1; oshape.push_back(v); out_elem *= static_cast<size_t>(v); }
        // Query TensorRT tensor data type to allocate correct size and set dtype
        nvinfer1::DataType tdt = nvinfer1::DataType::kFLOAT;
        try { tdt = impl_->engine->getTensorDataType(nm); } catch (...) {}
        size_t elem_size = 4; va::core::DType vdt = va::core::DType::F32;
        switch (tdt) {
            case nvinfer1::DataType::kHALF: elem_size = 2; vdt = va::core::DType::F16; break;
            case nvinfer1::DataType::kFLOAT: elem_size = 4; vdt = va::core::DType::F32; break;
            case nvinfer1::DataType::kINT32: elem_size = 4; vdt = va::core::DType::F32; break; // map to F32 (postproc expects float)
            default: elem_size = 4; vdt = va::core::DType::F32; break;
        }
        const size_t obytes = out_elem * elem_size;
        void* o_dev = nullptr;
        va::core::GpuBufferPool::Memory pooled_out{};
        if (impl_->device_pool) {
            pooled_out = impl_->device_pool->acquire(obytes);
            o_dev = pooled_out.ptr;
        }
        if (!o_dev) {
            if (cudaMalloc(&o_dev, obytes) != cudaSuccess) { VA_LOG_ERROR() << "cudaMalloc output failed"; return false; }
            impl_->staged_raw_cuda.push_back(o_dev);
        } else {
            // keep pooled buffer alive until next run
            impl_->staged_outputs.emplace_back(std::move(pooled_out));
        }
        if (!impl_->context->setTensorAddress(nm, o_dev)) {
            VA_LOG_ERROR() << "setTensorAddress(output) failed for " << nm;
            return false;
        }
        core::TensorView tv; tv.data = o_dev; tv.on_gpu = true; tv.dtype = vdt; tv.shape = std::move(oshape);
        outputs.push_back(tv);
    }
    // Enqueue
    cudaStream_t stream = impl_->cuda_stream ? reinterpret_cast<cudaStream_t>(impl_->cuda_stream) : 0;
    bool ok = impl_->context->enqueueV3(stream);
    if (!ok) { VA_LOG_ERROR() << "TensorRT enqueueV3 failed"; return false; }
    return true;
#else
    std::scoped_lock lock(impl_->mutex);
    if (!impl_->context || !impl_->engine) return false;
    if (input.shape.empty() || input.dtype != core::DType::F32 || !input.data) return false;
    // Recycle staged buffers from previous run
    if (impl_->device_pool && !impl_->staged_outputs.empty()) {
        for (auto &m : impl_->staged_outputs) impl_->device_pool->release(std::move(m));
        impl_->staged_outputs.clear();
    }
    for (void* p : impl_->staged_raw_cuda) { if (p) cudaFree(p); }
    impl_->staged_raw_cuda.clear();
    if (impl_->device_pool && !impl_->staged_inputs.empty()) {
        for (auto &m : impl_->staged_inputs) impl_->device_pool->release(std::move(m));
        impl_->staged_inputs.clear();
    }
    for (void* p : impl_->staged_input_raw) { if (p) cudaFree(p); }
    impl_->staged_input_raw.clear();
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
            impl_->staged_input_raw.push_back(in_dev);
        }
        cudaError_t err = cudaMemcpyAsync(in_dev, input.data, bytes, cudaMemcpyHostToDevice,
                            impl_->cuda_stream ? reinterpret_cast<cudaStream_t>(impl_->cuda_stream) : 0);
        if (err != cudaSuccess) { VA_LOG_ERROR() << "H2D failed"; return false; }
        if (pooled_in.ptr) {
            impl_->staged_inputs.emplace_back(std::move(pooled_in));
        }
    }
    bindings[inputIndex] = in_dev;

    // Allocate output buffers according to binding dims
    outputs.clear();
    for (int bi=0; bi<nb; ++bi) {
        if (impl_->engine->bindingIsInput(bi)) continue;
        auto bdims = impl_->context->getBindingDimensions(bi);
        size_t out_elem = 1; std::vector<int64_t> oshape; oshape.reserve(bdims.nbDims);
        for (int d=0; d<bdims.nbDims; ++d) { int v = bdims.d[d]; if (v<=0) v=1; oshape.push_back(v); out_elem *= static_cast<size_t>(v); }
        // Query binding data type for correct allocation and dtype reporting
        nvinfer1::DataType bdt = nvinfer1::DataType::kFLOAT; try { bdt = impl_->engine->getBindingDataType(bi); } catch (...) {}
        size_t elem_size = 4; va::core::DType vdt = va::core::DType::F32;
        switch (bdt) {
            case nvinfer1::DataType::kHALF: elem_size = 2; vdt = va::core::DType::F16; break;
            case nvinfer1::DataType::kFLOAT: elem_size = 4; vdt = va::core::DType::F32; break;
            case nvinfer1::DataType::kINT32: elem_size = 4; vdt = va::core::DType::F32; break; // map to F32 (postproc expects float)
            default: elem_size = 4; vdt = va::core::DType::F32; break;
        }
        const size_t obytes = out_elem * elem_size;
        void* o_dev = nullptr;
        va::core::GpuBufferPool::Memory pooled_out{};
        if (impl_->device_pool) {
            pooled_out = impl_->device_pool->acquire(obytes);
            o_dev = pooled_out.ptr;
        }
        if (!o_dev) {
            if (cudaMalloc(&o_dev, obytes) != cudaSuccess) { VA_LOG_ERROR() << "cudaMalloc output failed"; return false; }
            impl_->staged_raw_cuda.push_back(o_dev);
        } else {
            impl_->staged_outputs.emplace_back(std::move(pooled_out));
        }
        bindings[bi] = o_dev;
        core::TensorView tv; tv.data = o_dev; tv.on_gpu = true; tv.dtype = vdt; tv.shape = std::move(oshape);
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
