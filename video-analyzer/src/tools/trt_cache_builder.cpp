#include <iostream>
#include <string>
#include <vector>
#include <algorithm>
#include <filesystem>
#include <fstream>
#include <cstdlib>

#include <cuda_runtime.h>
#include <NvInfer.h>
#include <NvOnnxParser.h>
#if __has_include(<NvInferVersion.h>)
#include <NvInferVersion.h>
#endif

namespace {
struct Args {
    std::string model;
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
        else if (arg == "--fp16") a.fp16 = true;
        else if (arg == "--no-fp16") a.fp16 = false;
        else if (arg == "--workspace-mb" || arg == "-w") { try { a.workspace_mb = std::stoi(take(i)); } catch (...) {} }
        else if (arg == "--help" || arg == "-h") { return false; }
    }
    return !a.model.empty();
}

std::string cachePathForDevice(const std::string& dir) {
    int dev=0; cudaDeviceProp prop{}; if (cudaGetDevice(&dev)!=cudaSuccess) dev=0; if (cudaGetDeviceProperties(&prop, dev)!=cudaSuccess) { prop.major=0; prop.minor=0; }
    std::ostringstream oss; oss << dir << "/timing_sm" << (int)prop.major << (int)prop.minor << ".blob"; return oss.str();
}
}

int main(int argc, char** argv) {
    Args args;
    if (!parseArgs(argc, argv, args)) {
        std::cerr << "Usage: trt_cache_builder --model <onnx_path> [--fp16|--no-fp16] [--workspace-mb <MB>]" << std::endl;
        return 2;
    }
    if (!std::filesystem::exists(args.model)) {
        std::cerr << "Model not found: " << args.model << std::endl;
        return 3;
    }

    const char* envCacheDir = std::getenv("VA_TRT_CACHE_DIR");
    std::string cacheDir = envCacheDir? std::string(envCacheDir) : std::string("/app/.trt_native_cache");
    std::error_code ec; std::filesystem::create_directories(cacheDir, ec);

    TRTLogger logger(1000);
    try {
        // Builder/network/config
        nvinfer1::IBuilder* builder = nvinfer1::createInferBuilder(logger);
        if (!builder) throw std::runtime_error("createInferBuilder failed");
        uint32_t flags = 1u << static_cast<uint32_t>(nvinfer1::NetworkDefinitionCreationFlag::kEXPLICIT_BATCH);
        nvinfer1::INetworkDefinition* network = builder->createNetworkV2(flags);
        if (!network) throw std::runtime_error("createNetworkV2 failed");
        nvinfer1::IBuilderConfig* config = builder->createBuilderConfig();
        if (!config) throw std::runtime_error("createBuilderConfig failed");
        nvonnxparser::IParser* parser = nvonnxparser::createParser(*network, logger);
        if (!parser) throw std::runtime_error("createParser failed");

        // Parse ONNX
        if (!parser->parseFromFile(args.model.c_str(), static_cast<int>(nvinfer1::ILogger::Severity::kWARNING))) {
            throw std::runtime_error("nvonnxparser parse failed");
        }

        // Flags and workspace
        if (args.fp16) { try { config->setFlag(nvinfer1::BuilderFlag::kFP16); } catch (...) {} }
        const size_t workspace = static_cast<size_t>(args.workspace_mb) * 1024ull * 1024ull;
#if NV_TENSORRT_MAJOR >= 8
        if (workspace > 0) { try { config->setMemoryPoolLimit(nvinfer1::MemoryPoolType::kWORKSPACE, workspace); } catch (...) {} }
#else
        if (workspace > 0) { try { config->setMaxWorkspaceSize(workspace); } catch (...) {} }
#endif

        // Create (empty) timing cache and attach to config so getTimingCache() returns a handle after build
        try {
            nvinfer1::ITimingCache* empty = config->createTimingCache(nullptr, 0);
            if (empty) {
                config->setTimingCache(*empty, false /*ignoreMismatch*/);
            }
        } catch (...) { /* ignore */ }

        // Builder tuning knobs from env (optional)
        auto getEnvInt = [](const char* k, int defv){ if (const char* e = std::getenv(k)) { try { return std::stoi(e); } catch (...) {} } return defv; };
        try { config->setBuilderOptimizationLevel(getEnvInt("VA_TRT_BUILDER_OPT", 1)); } catch (...) {}
#if NV_TENSORRT_MAJOR < 10
        try { config->setMinTimingIterations(getEnvInt("VA_TRT_MIN_TIMING", 1)); } catch (...) {}
        try { config->setAvgTimingIterations(getEnvInt("VA_TRT_AVG_TIMING", 1)); } catch (...) {}
#else
        try { config->setAvgTimingIterations(getEnvInt("VA_TRT_AVG_TIMING", 1)); } catch (...) {}
#endif
        // Optional tactic sources from env
        if (const char* ts = std::getenv("VA_TRT_TACTIC_SOURCES")) {
            std::string v = toLower(ts);
            uint64_t mask = 0;
            if (v.find("cublaslt") != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS_LT));
            if (v.find("cublas")   != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUBLAS));
            if (v.find("cudnn")    != std::string::npos) mask |= (1ull << static_cast<int>(nvinfer1::TacticSource::kCUDNN));
            if (mask) { try { config->setTacticSources(mask); } catch (...) {} }
        }
        try { config->setProfilingVerbosity(nvinfer1::ProfilingVerbosity::kNONE); } catch (...) {}

        // Optimization profile for dynamic shapes (choose first input name or common guesses)
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

        // Build
        std::cout << "[INFO] Building TensorRT engine for: " << args.model << std::endl;
        nvinfer1::ICudaEngine* engine = builder->buildEngineWithConfig(*network, *config);
        if (!engine) throw std::runtime_error("buildEngineWithConfig failed");

        // Save timing cache for subsequent runs
        try {
            auto* tc = config->getTimingCache();
            if (tc) {
                nvinfer1::IHostMemory* mem = tc->serialize();
                if (mem && mem->size() > 0) {
                    std::filesystem::create_directories(cacheDir, ec);
                    std::string path = cachePathForDevice(cacheDir);
                    std::ofstream ofs(path, std::ios::binary);
                    ofs.write(static_cast<const char*>(mem->data()), mem->size());
                    ofs.close();
                    std::cout << "[INFO] Saved timing cache to: " << path << " size=" << mem->size() << std::endl;
                } else {
                    std::cout << "[WARN] Timing cache serialize returned empty" << std::endl;
                }
#if NV_TENSORRT_MAJOR < 10
                if (mem) mem->destroy();
#endif
            } else {
                std::cout << "[WARN] No timing cache available from config" << std::endl;
            }
        } catch (...) {
            std::cout << "[WARN] Exception while saving timing cache (ignored)" << std::endl;
        }

        // Cleanup (TRT 10+ managed by smart objects in background)
#if NV_TENSORRT_MAJOR < 10
        if (engine) engine->destroy();
        if (parser) parser->destroy();
        if (config) config->destroy();
        if (network) network->destroy();
        if (builder) builder->destroy();
#endif
        return 0;
    } catch (const std::exception& ex) {
        std::cerr << "[ERROR] TRT cache builder failed: " << ex.what() << std::endl;
        return 1;
    } catch (...) {
        std::cerr << "[ERROR] TRT cache builder failed: unknown exception" << std::endl;
        return 1;
    }
}
