#include "analyzer/triton_session.hpp"
#include "core/logger.hpp"
#include "analyzer/triton_metrics.hpp"
#include "analyzer/logging_util.hpp"

#if defined(USE_TRITON_CLIENT)
// Ensure CUDA runtime is included before Triton ipc to avoid typedef conflicts
#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_TRITON_HAVE_CUDA_RUNTIME 1
#    else
#      define VA_TRITON_HAVE_CUDA_RUNTIME 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_TRITON_HAVE_CUDA_RUNTIME 1
#  endif
#else
#  define VA_TRITON_HAVE_CUDA_RUNTIME 0
#endif

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

TritonGrpcModelSession::TritonGrpcModelSession(const Options& opt) : opt_(opt) {
#if defined(USE_TRITON_CLIENT)
    // 生成唯一的共享内存区名称，避免跨会话/跨流冲突
    std::ostringstream oss;
    oss << "va_in_dev" << opt_.device_id << "_" << std::hex << reinterpret_cast<std::uintptr_t>(this);
    in_shm_name_ = oss.str();
#endif
}
TritonGrpcModelSession::~TritonGrpcModelSession() {
#if defined(USE_TRITON_CLIENT)
#if VA_TRITON_HAVE_CUDA_RUNTIME
    if (shm_dev_buf_) {
        cudaFree(shm_dev_buf_);
        shm_dev_buf_ = nullptr; shm_capacity_ = 0;
    }
#endif
    if (client_) {
        (void)client_->UnregisterCudaSharedMemory(in_shm_name_);
        for (const auto& nm : out_shm_names_) {
            (void)client_->UnregisterCudaSharedMemory(nm);
        }
    }
    in_shm_bytes_ = 0; shm_registered_ = false;
#endif
}

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
#if VA_TRITON_HAVE_CUDA_RUNTIME
    // 固定 CUDA 设备，确保后续 cudaMalloc/cudaIpc* 在期望 device 上创建句柄
    {
        int cur=-1; (void)cudaGetDevice(&cur);
        if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id);
    }
#endif

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
    // 准备输出 SHM 名称（唯一定名），缓冲区延后按需分配
    try {
        const size_t n = opt_.output_names.size();
        out_shm_names_.resize(n);
        out_dev_bufs_.assign(n, nullptr);
        out_capacity_.assign(n, 0);
        out_bytes_.assign(n, 0);
        out_registered_.assign(n, false);
        for (size_t i=0;i<n;++i) {
            std::ostringstream oss; oss << in_shm_name_ << "_out" << i;
            out_shm_names_[i] = oss.str();
        }
    } catch (...) {}
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

        bool shm_bound = false;
#if VA_TRITON_HAVE_CUDA_RUNTIME
        if (opt_.use_cuda_shm && !in_shm_disabled_ && input.on_gpu) {
            // 确保当前 device 正确
            { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
            // 使用稳定的设备缓冲避免每帧更换指针造成重复注册
            if (shm_capacity_ < bytes) {
                if (shm_dev_buf_) cudaFree(shm_dev_buf_);
                if (cudaSuccess != cudaMalloc(&shm_dev_buf_, bytes)) {
                    shm_dev_buf_ = nullptr; shm_capacity_ = 0;
                } else {
                    shm_capacity_ = bytes; shm_registered_ = false;
                }
            }
            if (shm_dev_buf_) {
                // 注册一次（容量变化时重注）
                if (!shm_registered_) {
                    cudaIpcMemHandle_t ipc{};
                    if (cudaSuccess != cudaIpcGetMemHandle(&ipc, shm_dev_buf_)) {
                        va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_ipc");
                    } else {
                        // 先尝试反注册（即使不存在也忽略错误），避免服务端残留
                        (void)client_->UnregisterCudaSharedMemory(in_shm_name_);
                        const int dev_for_reg = (opt_.shm_server_device_id >= 0 ? opt_.shm_server_device_id : opt_.device_id);
                        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "analyzer.triton", 2000)
                            << "register input CUDA SHM name='" << in_shm_name_ << "' bytes=" << shm_capacity_
                            << " dev_for_reg=" << dev_for_reg << " local_dev=" << opt_.device_id;
                        auto er = client_->RegisterCudaSharedMemory(in_shm_name_, ipc, shm_capacity_, dev_for_reg);
                        if (!er.IsOk()) {
                            in_register_failures_++;
                            VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "analyzer.triton", 2000) << "RegisterCudaSharedMemory failed: " << er.Message();
                            va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_register");
                            // 不自动关闭 CUDA SHM；继续按 Host 路径绑定本帧，后续帧重试注册
                            if (opt_.shm_fail_disable_threshold > 0 && in_register_failures_ >= opt_.shm_fail_disable_threshold) {
                                in_shm_disabled_ = true;
                                VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton")
                                    << "disable CUDA SHM for inputs after " << in_register_failures_
                                    << " failures; falling back to host path. Hint: align CUDA_VISIBLE_DEVICES mapping or set 'triton_shm_server_device_id' in config.";
                            }
                        } else {
                            in_shm_bytes_ = shm_capacity_;
                            shm_registered_ = true; in_register_failures_ = 0;
                        }
                    }
                }
                // 将输入复制到稳定缓冲（D2D），然后绑定 SHM
                if (shm_registered_) {
                    // D2D 前再次确认 device
                    { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
                    if (cudaSuccess == cudaMemcpy(shm_dev_buf_, input.data, bytes, cudaMemcpyDeviceToDevice)) {
                        auto er2 = raw->SetSharedMemory(in_shm_name_, bytes, /*offset*/0);
                        if (er2.IsOk()) shm_bound = true; else va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_bind");
                    }
                }
            }
        }
#endif
        if (!shm_bound) {
            if (!raw->AppendRaw(host_ptr, bytes).IsOk()) return false;
        }
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
        // 若启用输出 SHM，绑定共享内存区；初始容量使用 triton_cuda_shm_bytes 或 8MB
#if VA_TRITON_HAVE_CUDA_RUNTIME
        size_t idx = &name - &opt_.output_names[0];
        if (opt_.use_cuda_shm && !out_shm_disabled_) {
            size_t need_cap = (opt_.cuda_shm_bytes > 0 ? (size_t)opt_.cuda_shm_bytes : (size_t)8*1024*1024);
            if (out_capacity_.size() <= idx) {
                // 防御：resize 到位
                const size_t n = opt_.output_names.size();
                out_dev_bufs_.resize(n, nullptr);
                out_capacity_.resize(n, 0);
                out_bytes_.resize(n, 0);
                out_registered_.resize(n, false);
                out_shm_names_.resize(n);
            }
            if (out_capacity_[idx] < need_cap) {
                if (out_dev_bufs_[idx]) cudaFree(out_dev_bufs_[idx]);
                { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
                if (cudaSuccess == cudaMalloc(&out_dev_bufs_[idx], need_cap)) {
                    out_capacity_[idx] = need_cap; out_registered_[idx] = false;
                } else {
                    out_dev_bufs_[idx] = nullptr; out_capacity_[idx] = 0; out_registered_[idx] = false;
                }
            }
            if (out_dev_bufs_[idx] && !out_registered_[idx]) {
                cudaIpcMemHandle_t ipc{};
                // 取句柄前固定 device，防止被外部切换
                { int cur=-1; (void)cudaGetDevice(&cur); if (cur != opt_.device_id) (void)cudaSetDevice(opt_.device_id); }
                if (cudaSuccess == cudaIpcGetMemHandle(&ipc, out_dev_bufs_[idx])) {
                    (void)client_->UnregisterCudaSharedMemory(out_shm_names_[idx]);
                    // 以配置优先：若指定 shm_server_device_id 则使用；否则回退到指针归属设备或本地 device_id
                    int dev_for_reg = (opt_.shm_server_device_id >= 0 ? opt_.shm_server_device_id : opt_.device_id);
                    // 若未指定覆盖，则尝试读取指针归属设备（同进程物理 ID），仅作保底
                    if (opt_.shm_server_device_id < 0) {
                        cudaPointerAttributes attr{};
                        if (cudaPointerGetAttributes(&attr, out_dev_bufs_[idx]) == cudaSuccess && attr.device >= 0) {
                            dev_for_reg = attr.device;
                        }
                    }
                    VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "analyzer.triton", 2000)
                        << "register output CUDA SHM name='" << out_shm_names_[idx] << "' bytes=" << out_capacity_[idx]
                        << " dev_for_reg=" << dev_for_reg << " local_dev=" << opt_.device_id;
                    auto er = client_->RegisterCudaSharedMemory(out_shm_names_[idx], ipc, out_capacity_[idx], dev_for_reg);
                    if (er.IsOk()) {
                        out_registered_[idx] = true;
                    } else {
                        out_register_failures_++;
                        va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_register");
                        VA_LOG_THROTTLED(::va::core::LogLevel::Warn, "analyzer.triton", 2000)
                            << "RegisterCudaSharedMemory(out) failed: " << er.Message();
                        if (opt_.shm_fail_disable_threshold > 0 && out_register_failures_ >= opt_.shm_fail_disable_threshold) {
                            out_shm_disabled_ = true;
                            VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton")
                                << "disable CUDA SHM for outputs after " << out_register_failures_
                                << " failures; falling back to host path. Hint: align CUDA_VISIBLE_DEVICES mapping or set 'triton_shm_server_device_id' in config.";
                        }
                    }
                } else {
                    va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_ipc");
                }
            }
            if (out_registered_[idx]) {
                // 绑定按需字节数（小于等于容量），避免超配导致 "invalid args"
                size_t bind_bytes = out_capacity_[idx];
                if (bind_bytes == 0 || bind_bytes > need_bytes) bind_bytes = need_bytes;
                auto er2 = out_raw->SetSharedMemory(out_shm_names_[idx], bind_bytes, /*offset*/0);
                if (!er2.IsOk()) { va::analyzer::metrics::triton_record_rpc(0.0, /*ok=*/false, "shm_bind"); }
            }
        }
#endif
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

    // Extract outputs（优先输出 SHM 的设备侧；若容量不足或未注册则回退 Host RawData）
    host_out_bufs_.clear();
    host_out_shapes_.clear();
    outputs.clear();
    size_t ok_out = 0;
    for (size_t i=0; i<opt_.output_names.size(); ++i) {
        const auto& name = opt_.output_names[i];
        const uint8_t* buf = nullptr; size_t nbytes = 0;
        auto rd = result->RawData(name, &buf, &nbytes);
        // 读取 shape
        std::vector<int64_t> shape;
        (void)result->Shape(name, &shape);
        // 若返回未包含 batch 维但我们输入含 batch=1，则前置一维 1 以与下游一致
        if (!input.shape.empty() && input.shape.size() == 4 && input.shape.front() == 1 && shape.size() == 2) {
            std::vector<int64_t> with_batch; with_batch.reserve(shape.size()+1);
            with_batch.push_back(1);
            with_batch.insert(with_batch.end(), shape.begin(), shape.end());
            shape.swap(with_batch);
        }
        size_t need_bytes = 0; for (auto d: shape) need_bytes = need_bytes ? need_bytes * (size_t)d : (size_t)d; need_bytes *= sizeof(float);
#if VA_TRITON_HAVE_CUDA_RUNTIME
        bool used_dev = false;
        if (opt_.use_cuda_shm && i < out_dev_bufs_.size() && out_registered_[i] && out_capacity_[i] >= need_bytes) {
            va::core::TensorView tv;
            tv.on_gpu = true;
            tv.dtype = va::core::DType::F32;
            tv.data = out_dev_bufs_[i];
            tv.shape = shape;
            outputs.push_back(tv);
            ok_out++; used_dev = true;
        }
        if (!used_dev)
#endif
        {
            if (!rd.IsOk() || !buf || nbytes == 0) {
                VA_LOG_C(::va::core::LogLevel::Warn, "analyzer.triton") << "no raw data for output '" << name << "' (ok=" << rd.IsOk() << ", bytes=" << nbytes << ")";
                continue;
            }
            host_out_bufs_.emplace_back(buf, buf + nbytes);
            host_out_shapes_.emplace_back(shape);
            va::core::TensorView tv;
            tv.on_gpu = false;
            tv.dtype = va::core::DType::F32;
            tv.data = host_out_bufs_.back().data();
            tv.shape = host_out_shapes_.back();
            outputs.push_back(tv);
            ++ok_out;
        }
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
