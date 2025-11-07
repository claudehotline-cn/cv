#include "analyzer/triton_session.hpp"
#include "core/logger.hpp"
#include "analyzer/triton_metrics.hpp"

#if defined(USE_TRITON_CLIENT)
#include <grpc_client.h>
using triton::client::InferenceServerGrpcClient;
using triton::client::InferInput;
using triton::client::InferOptions;
using triton::client::InferRequestedOutput;
using triton::client::InferResult;
#endif

namespace va::analyzer {

TritonGrpcModelSession::TritonGrpcModelSession(const Options& opt) : opt_(opt) {}
TritonGrpcModelSession::~TritonGrpcModelSession() = default;

bool TritonGrpcModelSession::loadModel(const std::string&, bool) {
#if defined(USE_TRITON_CLIENT)
    std::unique_ptr<InferenceServerGrpcClient> client;
    bool ok = InferenceServerGrpcClient::Create(&client, opt_.url, /*verbose*/false).IsOk();
    if (!ok) {
        VA_LOG_C(::va::core::LogLevel::Error, "analyzer.triton") << "connect failed url='" << opt_.url << "'";
        loaded_ = false;
        return false;
    }
    // 立即释放，仅用于连通性验证；run() 内部每次创建/复用隐式客户端由 Triton SDK 处理（最小实现）。
    loaded_ = true;
    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton") << "init: url='" << opt_.url << "' model='" << opt_.model_name << "'";
    return true;
#else
    VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton")
        << "Triton client is not enabled at build time (USE_TRITON_CLIENT=OFF)";
    loaded_ = false;
    return false;
#endif
}

bool TritonGrpcModelSession::run(const core::TensorView& input, std::vector<core::TensorView>& outputs) {
    outputs.clear();
#if defined(USE_TRITON_CLIENT)
    if (!loaded_) return false;
    // NOTE: 当前实现为同步创建 client；可在后续优化复用。
    std::unique_ptr<InferenceServerGrpcClient> client;
    if (!InferenceServerGrpcClient::Create(&client, opt_.url, /*verbose*/false).IsOk()) return false;

    // 构建 Infer 请求
    if (opt_.model_name.empty() || opt_.input_name.empty() || opt_.output_names.empty()) return false;

    if (!input.data || input.shape.empty() || input.dtype != va::core::DType::F32) {
        return false;
    }
    size_t elem = 1; for (auto d : input.shape) elem *= static_cast<size_t>(d);
    size_t bytes = elem * sizeof(float);

    // Inputs
    std::vector<std::unique_ptr<InferInput>> inps;
    {
        std::unique_ptr<InferInput> inp;
        if (!InferInput::Create(&inp, opt_.input_name, input.shape, "FP32").IsOk()) return false;
        if (!inp->AppendRaw(reinterpret_cast<const uint8_t*>(input.data), bytes).IsOk()) return false;
        inps.emplace_back(std::move(inp));
    }

    // Outputs
    std::vector<std::unique_ptr<InferRequestedOutput>> outs_req;
    outs_req.reserve(opt_.output_names.size());
    for (const auto& name : opt_.output_names) {
        std::unique_ptr<InferRequestedOutput> out;
        if (!InferRequestedOutput::Create(&out, name).IsOk()) return false;
        outs_req.emplace_back(std::move(out));
    }

    // Options
    InferOptions options(opt_.model_name);
    if (!opt_.model_version.empty()) options.model_version_ = opt_.model_version;

    std::shared_ptr<InferResult> result;
    auto t0 = std::chrono::high_resolution_clock::now();
    auto st = client->Infer(&result, options, inps, outs_req);
    auto t1 = std::chrono::high_resolution_clock::now();
    double sec = std::chrono::duration_cast<std::chrono::duration<double>>(t1 - t0).count();
    va::analyzer::metrics::triton_record_rpc(sec, st.IsOk());
    if (!st.IsOk()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "infer failed: " << st.Message();
        return false;
    }

    // Extract outputs
    host_out_bufs_.clear();
    host_out_shapes_.clear();
    outputs.clear();
    for (const auto& name : opt_.output_names) {
        const uint8_t* buf = nullptr; size_t nbytes = 0;
        if (!result->RawData(name, &buf, &nbytes).IsOk() || !buf || nbytes == 0) {
            continue;
        }
        std::vector<int64_t> shape;
        (void)result->Shape(name, &shape);
        host_out_bufs_.emplace_back(buf, buf + nbytes);
        host_out_shapes_.emplace_back(shape);
        va::core::TensorView tv;
        tv.on_gpu = false;
        tv.dtype = va::core::DType::F32; // 先按 FP32；后续可从 metadata 解析
        tv.data = host_out_bufs_.back().data();
        tv.shape = host_out_shapes_.back();
        outputs.push_back(tv);
    }
    return !outputs.empty();
#else
    return false;
#endif
}

IModelSession::ModelRuntimeInfo TritonGrpcModelSession::getRuntimeInfo() const {
    ModelRuntimeInfo info;
    info.provider = "triton-grpc";
    info.gpu_active = false; // T0: Host 内存路径；启用 CUDA SHM 后可置 true
    info.io_binding = false;
    info.device_binding = false;
    info.cpu_fallback = false;
    return info;
}

} // namespace va::analyzer
