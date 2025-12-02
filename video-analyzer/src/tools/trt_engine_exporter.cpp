#include <iostream>
#include <fstream>
#include <sstream>
#include <string>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <cstdlib>
#include <chrono>

#include <cuda_runtime.h>
#include <NvInfer.h>
#include <NvOnnxParser.h>
#if __has_include(<NvInferVersion.h>)
#include <NvInferVersion.h>
#endif

namespace {
struct Args {
    std::string model;         // ONNX path
    std::string output;        // .engine path (optional)
    bool fp16 {true};
    int workspace_mb {1024};
};

class TRTLogger : public nvinfer1::ILogger {
public:
    explicit TRTLogger(int throttle_ms = 1000) : throttle_ms_(throttle_ms) {}
    void log(Severity s, nvinfer1::AsciiChar const* msg) noexcept override {
        if (s == Severity::kERROR || s == Severity::kINTERNAL_ERROR) { std::cerr << "[ERROR][trt] " << msg << std::endl; return; }
        if (s == Severity::kWARNING) { std::cout << "[WARN][trt] " << msg << std::endl; return; }
        if (throttle_ms_ <= 0) { std::cout << "[INFO][trt] " << msg << std::endl; return; }
        const auto now = now_ms();
        auto last = last_ms_;
        if (now - last >= throttle_ms_) { last_ms_ = now; if (suppressed_ > 0) { std::cout << "[DEBUG][trt] [throttled] suppressed " << suppressed_ << " messages" << std::endl; suppressed_ = 0; } std::cout << "[DEBUG][trt] " << msg << std::endl; }
        else { ++suppressed_; }
    }
private:
    static long long now_ms() { using namespace std::chrono; return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count(); }
    int throttle_ms_ {1000};
    unsigned long long suppressed_ {0};
    long long last_ms_ {0};
};

std::string toLower(std::string s) { std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return (char)std::tolower(c); }); return s; }

bool parseArgs(int argc, char** argv, Args& a) {
    for (int i=1;i<argc;++i) {
        std::string arg = argv[i];
        auto take = [&](int& i){ return (i+1<argc)? std::string(argv[++i]) : std::string(); };
        if (arg == "--model" || arg == "-m") a.model = take(i);
        else if (arg == "--output" || arg == "-o") a.output = take(i);
        else if (arg == "--fp16") a.fp16 = true;
        else if (arg == "--no-fp16") a.fp16 = false;
        else if (arg == "--workspace-mb" || arg == "-w") { try { a.workspace_mb = std::stoi(take(i)); } catch (...) {} }
        else if (arg == "--help" || arg == "-h") { return false; }
    }
    return !a.model.empty();
}

std::string defaultEnginePathFor(const std::string& onnxPath) {
    std::filesystem::path p(onnxPath);
    std::string stem = p.stem().string();
    int dev=0; cudaDeviceProp prop{}; if (cudaGetDevice(&dev)!=cudaSuccess) dev=0; if (cudaGetDeviceProperties(&prop, dev)!=cudaSuccess) { prop.major=0; prop.minor=0; }
    std::ostringstream oss; oss << "/app/.trt_native_cache/engines/" << stem << "_sm" << (int)prop.major << (int)prop.minor << ("_fp16.engine");
    return oss.str();
}
}

int main(int argc, char** argv) {
    Args args;
    if (!parseArgs(argc, argv, args)) {
        std::cerr << "用法: trt_engine_exporter --model <onnx路径> [--output <engine路径>] [--fp16|--no-fp16] [--workspace-mb <MB>]" << std::endl;
        return 2;
    }
    if (!std::filesystem::exists(args.model)) {
        std::cerr << "模型不存在: " << args.model << std::endl;
        return 3;
    }
    if (args.output.empty()) {
        args.output = defaultEnginePathFor(args.model);
    }
    try { std::filesystem::create_directories(std::filesystem::path(args.output).parent_path()); } catch (...) {}

    TRTLogger logger(1000);
    try {
        // Builder/network/config
        nvinfer1::IBuilder* builder = nvinfer1::createInferBuilder(logger);
        if (!builder) throw std::runtime_error("createInferBuilder 失败");
        uint32_t flags = 1u << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
        nvinfer1::INetworkDefinition* network = builder->createNetworkV2(flags);
        if (!network) throw std::runtime_error("createNetworkV2 失败");
        nvinfer1::IBuilderConfig* config = builder->createBuilderConfig();
        if (!config) throw std::runtime_error("createBuilderConfig 失败");
        nvonnxparser::IParser* parser = nvonnxparser::createParser(*network, logger);
        if (!parser) throw std::runtime_error("createParser 失败");

        // 解析 ONNX
        if (!parser->parseFromFile(args.model.c_str(), static_cast<int>(nvinfer1::ILogger::Severity::kWARNING))) {
            throw std::runtime_error("nvonnxparser 解析失败");
        }

        // 构建参数
        if (args.fp16) { try { config->setFlag(nvinfer1::BuilderFlag::kFP16); } catch (...) {} }
        const size_t workspace = static_cast<size_t>(args.workspace_mb) * 1024ull * 1024ull;
#if NV_TENSORRT_MAJOR >= 8
        if (workspace > 0) { try { config->setMemoryPoolLimit(nvinfer1::MemoryPoolType::kWORKSPACE, workspace); } catch (...) {} }
#else
        if (workspace > 0) { try { config->setMaxWorkspaceSize(workspace); } catch (...) {} }
#endif

        // Timing cache：先创建空 cache，构建后可序列化
        try {
            nvinfer1::ITimingCache* empty = config->createTimingCache(nullptr, 0);
            if (empty) { config->setTimingCache(*empty, false); }
        } catch (...) {}

        // 环境可覆盖的优化参数（与 cache_builder 一致）
        auto getEnvInt = [](const char* k, int defv){ if (const char* e = std::getenv(k)) { try { return std::stoi(e); } catch (...) {} } return defv; };
        try { config->setBuilderOptimizationLevel(getEnvInt("VA_TRT_BUILDER_OPT", 1)); } catch (...) {}
#if NV_TENSORRT_MAJOR < 10
        try { config->setMinTimingIterations(getEnvInt("VA_TRT_MIN_TIMING", 1)); } catch (...) {}
        try { config->setAvgTimingIterations(getEnvInt("VA_TRT_AVG_TIMING", 1)); } catch (...) {}
#else
        try { config->setAvgTimingIterations(getEnvInt("VA_TRT_AVG_TIMING", 1)); } catch (...) {}
#endif
        if (const char* ts = std::getenv("VA_TRT_TACTIC_SOURCES")) {
            std::string v = toLower(ts); uint64_t mask = 0;
#ifdef NV_TENSORRT_MAJOR
            if (v.find("cublaslt") != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS_LT));
            if (v.find("cublas")   != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS));
            if (v.find("cudnn")    != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUDNN));
            if (mask) { try { config->setTacticSources(mask); } catch (...) {} }
#endif
        }
        try { config->setProfilingVerbosity(nvinfer1::ProfilingVerbosity::kNONE); } catch (...) {}

        // 动态形状优化 profile（常见 1x3x640x640）
        const char* inName = nullptr;
        try { if (network->getNbInputs() > 0) { auto* in = network->getInput(0); if (in) inName = in->getName(); } } catch (...) { inName=nullptr; }
        if (!inName) { static const char* guesses[] = {"images","input","data","input_0","inputs"}; for (auto g:guesses){ inName=g; break; } }
        if (inName) {
            nvinfer1::IOptimizationProfile* prof = builder->createOptimizationProfile();
            nvinfer1::Dims minD{4, {1,3,640,640}}; nvinfer1::Dims optD{4, {1,3,640,640}}; nvinfer1::Dims maxD{4, {1,3,640,640}};
            bool ok = prof->setDimensions(inName, nvinfer1::OptProfileSelector::kMIN, minD)
                    && prof->setDimensions(inName, nvinfer1::OptProfileSelector::kOPT, optD)
                    && prof->setDimensions(inName, nvinfer1::OptProfileSelector::kMAX, maxD);
            if (ok) { try { config->addOptimizationProfile(prof); } catch (...) {} }
        }

        // 构建引擎
        std::cout << "[INFO] Building TensorRT engine for: " << args.model << std::endl;
        nvinfer1::ICudaEngine* engine = builder->buildEngineWithConfig(*network, *config);
        if (!engine) throw std::runtime_error("buildEngineWithConfig 失败");

        // 序列化 .engine
        nvinfer1::IHostMemory* plan = engine->serialize();
        if (!plan || plan->size() == 0) throw std::runtime_error("engine.serialize 返回空");
        {
            std::ofstream ofs(args.output, std::ios::binary);
            ofs.write(static_cast<const char*>(plan->data()), plan->size());
            ofs.close();
            std::cout << "[INFO] Saved engine to: " << args.output << " size=" << plan->size() << std::endl;
        }
#if NV_TENSORRT_MAJOR < 10
        if (plan) plan->destroy();
#endif

        // 也尽量保存 timing cache（可选）
        try {
            auto* tc = config->getTimingCache();
            if (tc) {
                nvinfer1::IHostMemory* mem = tc->serialize();
                if (mem && mem->size() > 0) {
                    std::string dir = "/app/.trt_native_cache";
                    if (const char* d = std::getenv("VA_TRT_CACHE_DIR")) dir = d;
                    std::error_code ec; std::filesystem::create_directories(dir, ec);
                    int dev=0; cudaDeviceProp prop{}; if (cudaGetDevice(&dev)!=cudaSuccess) dev=0; if (cudaGetDeviceProperties(&prop, dev)!=cudaSuccess) { prop.major=0; prop.minor=0; }
                    std::ostringstream oss; oss << dir << "/timing_sm" << (int)prop.major << (int)prop.minor << ".blob";
                    std::ofstream ofs(oss.str(), std::ios::binary);
                    ofs.write(static_cast<const char*>(mem->data()), mem->size());
                    ofs.close();
                    std::cout << "[INFO] Saved timing cache to: " << oss.str() << " size=" << mem->size() << std::endl;
#if NV_TENSORRT_MAJOR < 10
                    mem->destroy();
#endif
                }
            }
        } catch (...) {
            std::cout << "[WARN] 保存 timing cache 失败（可忽略）" << std::endl;
        }

        // 清理
#if NV_TENSORRT_MAJOR < 10
        if (engine) engine->destroy();
        if (parser) parser->destroy();
        if (config) config->destroy();
        if (network) network->destroy();
        if (builder) builder->destroy();
#endif
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "[ERROR] TRT engine exporter 失败: " << ex.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "[ERROR] TRT engine exporter 失败: 未知异常" << std::endl;
        return 1;
    }
}

