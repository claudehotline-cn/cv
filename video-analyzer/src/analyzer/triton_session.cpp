#include "analyzer/triton_session.hpp"
#include "core/logger.hpp"
#include "analyzer/triton_metrics.hpp"
#include "analyzer/logging_util.hpp"

#if defined(USE_TRITON_CLIENT)
#include <grpc_client.h>
#if defined(__has_include)
#  if __has_include(<grpc_service.pb.h>)
#    include <grpc_service.pb.h>
#    define VA_HAS_TRT_GRPC_PB 1
#  else
#    define VA_HAS_TRT_GRPC_PB 0
#  endif
#else
#  define VA_HAS_TRT_GRPC_PB 0
#endif
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
    // 持久化客户端以复用连接
    client_ = std::move(client);
    loaded_ = true;
    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton") << "init: url='" << opt_.url << "' model='" << opt_.model_name << "'";

#if VA_HAS_TRT_GRPC_PB
    // 元数据自适配：尝试拉取 ModelMetadata，自动填充 IO 名称（避免配置不一致）
    if (!opt_.model_name.empty()) {
        inference::ModelMetadataResponse md;
        auto st_md = client_->ModelMetadata(&md, opt_.model_name, opt_.model_version);
        if (st_md.IsOk()) {
            try {
                if (opt_.input_name.empty() && md.inputs_size() > 0) {
                    opt_.input_name = md.inputs(0).name();
                    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton") << "autofill input_name='" << opt_.input_name << "' from metadata";
                }
                if (opt_.output_names.empty() && md.outputs_size() > 0) {
                    opt_.output_names.clear();
                    const int n = md.outputs_size();
                    for (int i = 0; i < n; ++i) opt_.output_names.push_back(md.outputs(i).name());
                    VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton") << "autofill outputs (n=" << n << ") from metadata";
                }
            } catch (...) { /* ignore metadata parse errors */ }
        } else {
            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "metadata fetch failed: " << st_md.Message();
        }
    }
#endif
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
    // 复用持久化客户端，缺失则重建一次并记录失败日志
    if (!client_) {
        std::unique_ptr<InferenceServerGrpcClient> c2;
        if (!InferenceServerGrpcClient::Create(&c2, opt_.url, /*verbose*/false).IsOk()) {
            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "client create failed url='" << opt_.url << "'";
            va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "create");
            return false;
        }
        client_ = std::move(c2);
    }

    // 构建 Infer 请求
    if (opt_.model_name.empty() || opt_.input_name.empty() || opt_.output_names.empty()) return false;

    if (!input.data || input.shape.empty() || input.dtype != va::core::DType::F32) {
        va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "invalid_input");
        return false;
    }
    size_t elem = 1; for (auto d : input.shape) elem *= static_cast<size_t>(d);
    size_t bytes = elem * sizeof(float);

    const uint8_t* host_ptr = reinterpret_cast<const uint8_t*>(input.data);
    std::vector<uint8_t> host_stage;
#if defined(USE_CUDA)
    if (input.on_gpu) {
        host_stage.resize(bytes);
        auto err = cudaMemcpy(host_stage.data(), input.data, bytes, cudaMemcpyDeviceToHost);
        if (err != cudaSuccess) {
            VA_LOG_C(::va::core::LogLevel::Error, "analyzer.triton") << "cudaMemcpy D2H failed: " << cudaGetErrorString(err);
            return false;
        }
        host_ptr = host_stage.data();
    }
#else
    if (input.on_gpu) {
        VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "input is on GPU but CUDA not enabled; cannot stage to host";
        return false;
    }
#endif

    // Inputs (Triton 25.08 API: Create(InferInput**), Infer expects vector<InferInput*>)
    std::vector<std::shared_ptr<InferInput>> inps_owner;
    std::vector<InferInput*> inps;
    {
        // Log input shape snapshot for diagnostics (throttled)
        std::string s; for (size_t i=0;i<input.shape.size();++i){ s += (i?"x":""); s += std::to_string(input.shape[i]); }
        auto lvl = va::analyzer::logutil::log_level_for_tag("analyzer.triton", ::va::core::LogLevel::Info);
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("analyzer.triton", 1000);
        VA_LOG_THROTTLED(lvl, "analyzer.triton", thr) << "run in_shape=" << s << " on_gpu=" << std::boolalpha << input.on_gpu;
        // T0: 若模型为非 batch（config 无 max_batch_size），而输入 shape 带 1 的 batch 维，则去掉 batch 维
        std::vector<int64_t> send_shape = input.shape;
        if (opt_.assume_no_batch) {
            if (send_shape.size() == 4 && send_shape.front() == 1) {
                send_shape.erase(send_shape.begin());
            }
        }
        InferInput* raw = nullptr;
        if (!InferInput::Create(&raw, opt_.input_name, send_shape, "FP32").IsOk()) {
            va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "mk_input");
            return false;
        }
        inps_owner.emplace_back(raw); // managed by shared_ptr (delete on scope exit)
        if (!raw->AppendRaw(host_ptr, bytes).IsOk()) return false;
        inps.push_back(raw);
    }

    // Outputs (Create(InferRequestedOutput**), Infer expects vector<const InferRequestedOutput*>)
    std::vector<std::shared_ptr<InferRequestedOutput>> outs_owner;
    std::vector<const InferRequestedOutput*> outs_req;
    outs_owner.reserve(opt_.output_names.size());
    outs_req.reserve(opt_.output_names.size());
    for (const auto& name : opt_.output_names) {
        InferRequestedOutput* out_raw = nullptr;
        if (!InferRequestedOutput::Create(&out_raw, name).IsOk()) {
            va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "mk_output");
            return false;
        }
        outs_owner.emplace_back(out_raw);
        outs_req.push_back(out_raw);
    }

    // Options
    InferOptions options(opt_.model_name);
    if (!opt_.model_version.empty()) options.model_version_ = opt_.model_version;

    // Triton 25.08 API: Infer(InferResult** ...)
    InferResult* result_raw = nullptr;
    auto do_infer = [&](InferResult** out_res) {
        auto t0 = std::chrono::high_resolution_clock::now();
        auto st = client_->Infer(out_res, options, inps, outs_req);
        auto t1 = std::chrono::high_resolution_clock::now();
        double sec = std::chrono::duration_cast<std::chrono::duration<double>>(t1 - t0).count();
        va::analyzer::metrics::triton_record_rpc(sec, st.IsOk(), st.IsOk()? nullptr : "infer");
        return st;
    };

    auto st = do_infer(&result_raw);
    if (!st.IsOk()) {
        std::string msg = st.Message();
        VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "infer failed: " << msg;
        // 自适配：若报 batch-size 相关错误且当前假定为无 batch，则切换为保留 batch 再重试一次
        bool will_retry = false;
        if (opt_.assume_no_batch) {
            std::string m = msg; for (auto& c : m) c = (char)std::tolower((unsigned char)c);
            if (m.find("batch-size") != std::string::npos || m.find("batch size") != std::string::npos) {
                VA_LOG_C(::va::core::LogLevel::Info, "analyzer.triton") << "retry with batch dimension kept (auto-adapt)";
                opt_.assume_no_batch = false;
                will_retry = true;
            }
        }
        if (will_retry) {
            // rebuild inputs with batch kept
            inps_owner.clear(); inps.clear();
            InferInput* raw = nullptr;
            if (!InferInput::Create(&raw, opt_.input_name, input.shape, "FP32").IsOk()) {
                return false;
            }
            inps_owner.emplace_back(raw);
            if (!raw->AppendRaw(host_ptr, bytes).IsOk()) return false;
            inps.push_back(raw);
            result_raw = nullptr; st = do_infer(&result_raw);
            if (!st.IsOk()) {
                VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "infer failed after retry: " << st.Message();
                return false;
            }
        } else {
            return false;
        }
    }
    std::unique_ptr<InferResult> result(result_raw); // manage lifetime

    // Extract outputs
    host_out_bufs_.clear();
    host_out_shapes_.clear();
    outputs.clear();
    size_t ok_out = 0;
    for (const auto& name : opt_.output_names) {
        const uint8_t* buf = nullptr; size_t nbytes = 0;
        auto rd = result->RawData(name, &buf, &nbytes);
        if (!rd.IsOk() || !buf || nbytes == 0) {
            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "no raw data for output '" << name << "' (ok=" << rd.IsOk() << ", bytes=" << nbytes << ")";
            continue;
        }
        std::vector<int64_t> shape;
        (void)result->Shape(name, &shape);
        // 若返回未包含 batch 维但我们输入含 batch=1，则前置一维 1 以与下游一致
        if (!input.shape.empty() && input.shape.size() == 4 && input.shape.front() == 1 && shape.size() == 2) {
            std::vector<int64_t> with_batch; with_batch.reserve(shape.size()+1);
            with_batch.push_back(1);
            with_batch.insert(with_batch.end(), shape.begin(), shape.end());
            shape.swap(with_batch);
        }
        host_out_bufs_.emplace_back(buf, buf + nbytes);
        host_out_shapes_.emplace_back(shape);
        va::core::TensorView tv;
        tv.on_gpu = false;
        tv.dtype = va::core::DType::F32; // 先按 FP32；后续可从 metadata 解析
        tv.data = host_out_bufs_.back().data();
        tv.shape = host_out_shapes_.back();
        outputs.push_back(tv);
        ++ok_out;
    }
    if (ok_out == 0) {
        VA_LOG_C(::va::core::LogLevel::Error, "analyzer.triton") << "infer returned no outputs for requested names (n=" << opt_.output_names.size() << ")";
        va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "no_output");
        return false;
    }
    return true;
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
