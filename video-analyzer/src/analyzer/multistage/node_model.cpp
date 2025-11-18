#include "analyzer/multistage/node_model.hpp"
#include "analyzer/model_session_factory.hpp"
#include "analyzer/load_metrics.hpp"
#include "core/engine_manager.hpp"
#include "analyzer/logging_util.hpp"
#include <algorithm>
#include <chrono>
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"

#ifdef USE_CUDA
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_NODE_MODEL_HAS_CUDA 1
#    else
#      define VA_MS_NODE_MODEL_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_NODE_MODEL_HAS_CUDA 1
#  endif
#else
#  define VA_MS_NODE_MODEL_HAS_CUDA 0
#endif

using va::analyzer::multistage::util::get_or;

namespace va { namespace analyzer { namespace multistage {

NodeModel::NodeModel(const std::unordered_map<std::string,std::string>& cfg) {
    auto itIn = cfg.find("in"); if (itIn != cfg.end()) in_key_ = itIn->second;
    auto itOuts = cfg.find("outs");
    if (itOuts != cfg.end()) {
        out_keys_.clear();
        auto list = va::analyzer::multistage::util::split_csv(itOuts->second);
        if (list.empty()) {
            out_keys_.push_back(itOuts->second);
        } else {
            out_keys_.insert(out_keys_.end(), list.begin(), list.end());
        }
    }
    auto itPath = cfg.find("model_path"); if (itPath != cfg.end()) model_path_ = itPath->second;
    if (auto itT = cfg.find("model_path_trt"); itT != cfg.end()) model_path_trt_ = itT->second;
    if (auto itO = cfg.find("model_path_ort"); itO != cfg.end()) model_path_ort_ = itO->second;
    if (auto itTi = cfg.find("model_path_triton"); itTi != cfg.end()) model_path_triton_ = itTi->second;
    // Optional per-node provider override (e.g., reid 使用 cuda，det 使用 triton)
    if (auto itFp = cfg.find("force_provider"); itFp != cfg.end()) force_provider_override_ = itFp->second;
    // Optional per-node Triton 输入名 / 输出名 / GPU 输出覆盖（例如 det 节点固定 input=images, output0）
    if (auto itTi = cfg.find("triton_input"); itTi != cfg.end()) triton_input_override_ = itTi->second;
    if (auto itTo = cfg.find("triton_outputs"); itTo != cfg.end()) triton_outputs_override_ = itTo->second;
    if (auto itGo = cfg.find("triton_gpu_output"); itGo != cfg.end()) triton_gpu_output_override_ = itGo->second;
    // 可选：对 ROI batch 输入的模型启用“按 ROI 顺序逐个推理”（用于 max_batch_size=1 的 ReID 模型）
    if (auto itSeq = cfg.find("roi_seq_batch"); itSeq != cfg.end()) {
        auto v = itSeq->second;
        std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){ return (char)std::tolower(c); });
        roi_seq_batch_ = (v=="1" || v=="true" || v=="yes" || v=="on");
    }
}

bool NodeModel::open(NodeContext& ctx) {
    if (session_) return true;

    // Create model session via factory (encapsulates provider priority and options mapping)
    va::core::EngineDescriptor desc;
    if (ctx.engine_registry) {
        try { desc = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry)->currentEngine(); }
        catch (...) { /* ignore */ }
    }
    // Node-level provider override: allow certain nodes (e.g., reid) to use a different provider
    // while keeping engine-level force_provider=triton for others（如 det）
    if (!force_provider_override_.empty()) {
        try { desc.options["force_provider"] = force_provider_override_; } catch (...) { /* ignore */ }
    }
    // 当使用 Triton provider 时，允许通过 graph 参数覆盖 triton_model（按模型目录名）
    if (!model_path_triton_.empty()) {
        try { desc.options["triton_model"] = model_path_triton_; } catch (...) { /* ignore */ }
    }
    // 当使用 Triton provider 时，允许通过 graph 参数覆盖 triton_input / triton_outputs / triton_gpu_output（按模型 IO 名）
    if (!triton_input_override_.empty()) {
        try { desc.options["triton_input"] = triton_input_override_; } catch (...) { /* ignore */ }
    }
    if (!triton_outputs_override_.empty()) {
        try { desc.options["triton_outputs"] = triton_outputs_override_; } catch (...) { /* ignore */ }
    }
    if (!triton_gpu_output_override_.empty()) {
        try { desc.options["triton_gpu_output"] = triton_gpu_output_override_; } catch (...) { /* ignore */ }
    }

    auto now_ms = [](){ using namespace std::chrono; return duration_cast<milliseconds>(steady_clock::now().time_since_epoch()).count(); };

    auto pick_path_for = [&](const std::string& prov)->std::string{
        std::string p = model_path_;
        std::string v = prov;
        std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
        if ((v=="tensorrt-native" || v=="tensorrt_native" || v=="trt-native") && !model_path_trt_.empty())
            return model_path_trt_;
        // Triton In-Process / gRPC 均不依赖本地 ONNX 路径，使用占位符避免误用本地模型路径
        if (v=="triton" || v=="triton-inproc" || v=="triton_grpc" || v=="triton-grpc")
            return std::string("__triton__");
        if (!model_path_ort_.empty()) return model_path_ort_;
        return p;
    };

    // Primary decision
    ProviderDecision dec{};
    (void)va::analyzer::create_model_session(desc, ctx, &dec);
    std::string primary = dec.resolved;
    // Build fallback chain (no CPU fallback to avoid GPU→CPU tensor mismatch)
    std::vector<std::string> chain;
    auto norm = [](std::string s){ std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){return (char)std::tolower(c);} ); return s; };
    primary = norm(primary);
    if (primary == "tensorrt-native") { chain = {"tensorrt-native","triton","tensorrt","cuda"}; }
    else if (primary == "tensorrt")   { chain = {"tensorrt","triton","cuda"}; }
    else if (primary == "triton")     { chain = {"triton","tensorrt","cuda"}; }
    else if (primary == "cuda")       { chain = {"cuda"}; }
    else { chain = {"cuda"}; }

    // Optional override via engine option: force_provider / providers
    try {
        auto it_force = desc.options.find("force_provider");
        if (it_force != desc.options.end()) {
            std::string v = norm(it_force->second);
            if (!v.empty()) {
                chain.clear(); chain.push_back(v);
                VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model") << "provider chain overridden by force_provider='" << v << "'";
            }
        } else if (auto it_p = desc.options.find("providers"); it_p != desc.options.end()) {
            // comma/semicolon separated list
            chain.clear(); std::string cur; for (char c : it_p->second){ if (c==','||c==';'){ if(!cur.empty()){ chain.push_back(norm(cur)); cur.clear(); } } else cur.push_back(c);} if(!cur.empty()) chain.push_back(norm(cur));
            if (chain.empty()) chain.push_back(primary);
            VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model") << "provider chain overridden by providers option (n=" << chain.size() << ")";
        }
    } catch (...) { /* ignore */ }

    std::shared_ptr<IModelSession> loaded;
    std::string used_provider;
    for (const auto& prov : chain) {
        va::core::EngineDescriptor tryd = desc; tryd.provider = prov;
        ProviderDecision d2{};
        auto cand = va::analyzer::create_model_session(tryd, ctx, &d2);
        // 根据会话“实际解析后的 provider”选择模型路径，避免 Triton 客户端未启用时仍使用“__triton__”占位路径
        std::string prov_resolved = d2.resolved.empty() ? prov : d2.resolved;
        std::string path = pick_path_for(prov_resolved);
        // 对于本地会话，空路径视为配置错误；Triton 使用占位路径允许继续
        if (path.empty() && prov != "triton") continue;
        VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model")
            << "open: model_path='" << path << "' provider_try='" << prov << "' device_id=" << tryd.device_index;
        auto t0 = now_ms();
        bool ok = cand->loadModel(path, /*use_gpu*/false);
        auto t1 = now_ms();
        va::analyzer::metrics::record_model_session_load(static_cast<double>(t1 - t0) / 1000.0, ok);
        if (!ok) {
            VA_LOG_C(::va::core::LogLevel::Warn, "ms.node_model") << "load failed provider='" << prov << "' path='" << path << "'";
            continue; // try next
        }
        // Validate outputs declared
        try {
            auto out_names_probe = cand->outputNames();
            // 对于 Triton 路径（尤其是 In‑Process），允许在 load 阶段输出名为空，
            // 由后续推理过程基于响应自动填充真实输出名。
            std::string prov_lower = prov_resolved;
            std::transform(prov_lower.begin(), prov_lower.end(), prov_lower.begin(),
                           [](unsigned char c){ return (char)std::tolower(c); });
            bool is_triton_like = (prov_lower == "triton" ||
                                   prov_lower == "triton-inproc" ||
                                   prov_lower == "triton-grpc");
            if (!is_triton_like) {
                if (out_names_probe.empty()) {
                    VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                        << "model has zero declared outputs (path='" << model_path_ << "'). Check ONNX export.";
                    continue;
                }
            }
        } catch (...) {}
        loaded = std::move(cand); used_provider = prov_resolved; break;
    }
    if (!loaded) {
        VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model") << "all providers failed after fallback chain";
        return false;
    }

    // 回填 EngineManager 的运行态（provider/gpu/io_binding/device_binding），用于 RuntimeSummary
    if (ctx.engine_registry) {
        try {
            auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
            auto ri = loaded->getRuntimeInfo();
            va::core::EngineRuntimeStatus st;
            st.provider = ri.provider;
            st.gpu_active = ri.gpu_active;
            st.io_binding = ri.io_binding;
            st.device_binding = ri.device_binding;
            st.cpu_fallback = ri.cpu_fallback;
            em->updateRuntimeStatus(std::move(st));
            VA_LOG_C(::va::core::LogLevel::Info, "app") << "[RuntimeSummary][post-open] provider=" << ri.provider
                << " gpu_active=" << std::boolalpha << ri.gpu_active
                << " io_binding=" << ri.io_binding
                << " device_binding=" << ri.device_binding;
        } catch (...) { /* best-effort */ }
    }
    // 输出名统计
    try {
        auto names = loaded->outputNames();
        VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model") << "outputs_declared=" << names.size();
    } catch (...) {}

    session_ = std::move(loaded);
    return true;
}

// 释放顺序 ReID 聚合使用的 GPU 特征缓冲
static void release_roi_seq_gpu_mem(va::core::GpuBufferPool::Memory& mem, NodeContext& ctx) {
    if (mem.ptr && ctx.gpu_pool) {
        ctx.gpu_pool->release(std::move(mem));
    }
}

bool NodeModel::process(Packet& p, NodeContext& ctx) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) {
        // 对于以 ROI batch 作为输入的模型节点（如 ReID、ROI 分类），
        // 在本帧没有 ROI（上游未产出 tensor:roi_batch）时视为“空集合”，不将其视为错误，直接跳过该节点。
        if (roi_seq_batch_ && in_key_ == "tensor:roi_batch") {
            return true;
        }
        return false;
    }

    std::vector<va::core::TensorView> outs;
    // 针对启用了 roi_seq_batch 的节点（例如 max_batch_size=1 的 ReID），
    // 将 [N,3,H,W] 的 ROI batch 拆成 N 次单独推理，并在 CPU 上聚合为 [N,D] 特征。
    if (roi_seq_batch_ && in_key_ == "tensor:roi_batch") {
        const auto& in_tv = it->second;
        if (in_tv.shape.size() != 4) {
            infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
            VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                << "roi_seq_batch enabled but input rank != 4 (path='" << model_path_ << "').";
            return false;
        }
        const int64_t N = in_tv.shape[0];
        const int64_t C = in_tv.shape[1];
        const int64_t H = in_tv.shape[2];
        const int64_t W = in_tv.shape[3];
        if (N <= 0) {
            // 空 ROI 集合：直接跳过
            return true;
        }
        const size_t plane = static_cast<size_t>(C) * static_cast<size_t>(H) * static_cast<size_t>(W);
        const size_t elems_per_sample = plane;
        roi_seq_feat_buf_.clear();
        int feat_dim = -1;
        bool agg_on_gpu = false;
        float* d_feats_base = nullptr;
        for (int64_t i = 0; i < N; ++i) {
            va::core::TensorView single = in_tv;
            single.shape[0] = 1;
            // 假定为连续的 NCHW/FP32 布局；原始 data 为 void*，此处仅重定位起始地址
            const float* base = static_cast<const float*>(in_tv.data);
            float* sample_ptr = const_cast<float*>(base + i * elems_per_sample);
            single.data = static_cast<void*>(sample_ptr);
            std::vector<va::core::TensorView> tmp_outs;
            if (!session_ || !session_->run(single, tmp_outs) || tmp_outs.empty()) {
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "roi_seq_batch: sub-inference failed at index " << i
                    << " (path='" << model_path_ << "').";
                return false;
            }
            const auto& t = tmp_outs[0];
            if (t.dtype != va::core::DType::F32) {
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "roi_seq_batch: output dtype is not F32 (path='" << model_path_ << "').";
                return false;
            }
            int cur_feat_dim = 0;
            const std::size_t rank = t.shape.size();
            if (rank >= 2) {
                // 允许 [1,D] 或 [1,C,H,W] 等任意 rank>=2 的形状，统一将除 batch 维之外的维度展平为特征维度
                if (t.shape[0] != 1) {
                    infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                    VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                        << "roi_seq_batch: expected first dim==1 but got " << t.shape[0]
                        << " (path='" << model_path_ << "').";
                    return false;
                }
                int64_t prod = 1;
                for (std::size_t k = 1; k < rank; ++k) {
                    prod *= t.shape[k];
                }
                cur_feat_dim = static_cast<int>(prod);
            } else if (rank == 1) {
                // [D]
                cur_feat_dim = static_cast<int>(t.shape[0]);
            } else {
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "roi_seq_batch: unsupported output rank=" << rank
                    << " (path='" << model_path_ << "').";
                return false;
            }
            if (cur_feat_dim <= 0) {
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "roi_seq_batch: invalid feature dim " << cur_feat_dim
                    << " (path='" << model_path_ << "').";
                return false;
            }
            if (feat_dim < 0) {
                feat_dim = cur_feat_dim;
                // 首次确定特征维度后，决定聚合位置（GPU 或 CPU）
                if (t.on_gpu && ctx.gpu_pool && VA_MS_NODE_MODEL_HAS_CUDA) {
#if VA_MS_NODE_MODEL_HAS_CUDA
                    // 若现有聚合缓冲不足以容纳 [N,D]，则通过池子重新获取更大的缓冲
                    const std::size_t needed_bytes = static_cast<std::size_t>(N) * static_cast<std::size_t>(feat_dim) * sizeof(float);
                    if (!roi_seq_gpu_mem_.ptr || roi_seq_gpu_mem_.bytes < needed_bytes) {
                        release_roi_seq_gpu_mem(roi_seq_gpu_mem_, ctx);
                        roi_seq_gpu_mem_ = ctx.gpu_pool->acquire(needed_bytes);
                    }
                    if (roi_seq_gpu_mem_.ptr) {
                        d_feats_base = static_cast<float*>(roi_seq_gpu_mem_.ptr);
                        agg_on_gpu = true;
                    } else {
                        agg_on_gpu = false;
                    }
#else
                    agg_on_gpu = false;
#endif
                } else {
                    agg_on_gpu = false;
                }
                if (!agg_on_gpu) {
                    roi_seq_feat_buf_.reserve(static_cast<size_t>(N) * static_cast<size_t>(feat_dim));
                }
            } else if (cur_feat_dim != feat_dim) {
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "roi_seq_batch: inconsistent feature dim " << cur_feat_dim
                    << " vs " << feat_dim << " (path='" << model_path_ << "').";
                return false;
            }
            if (agg_on_gpu) {
#if VA_MS_NODE_MODEL_HAS_CUDA
                if (!d_feats_base) {
                    infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                    VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                        << "roi_seq_batch: GPU aggregation selected but d_feats_base is null (path='" << model_path_ << "').";
                    return false;
                }
                auto err = cudaMemcpyAsync(
                    d_feats_base + static_cast<std::size_t>(i) * static_cast<std::size_t>(feat_dim),
                    t.data,
                    static_cast<std::size_t>(feat_dim) * sizeof(float),
                    cudaMemcpyDeviceToDevice,
                    static_cast<cudaStream_t>(ctx.stream));
                if (err != cudaSuccess) {
                    infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                    VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                        << "roi_seq_batch: cudaMemcpyAsync D2D failed (" << cudaGetErrorString(err)
                        << ") path='" << model_path_ << "'.";
                    return false;
                }
#else
                (void)d_feats_base;
                infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
                return false;
#endif
            } else {
                const float* src = static_cast<const float*>(t.data);
                roi_seq_feat_buf_.insert(roi_seq_feat_buf_.end(), src, src + feat_dim);
            }
        }
        if (feat_dim <= 0) {
            infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
        va::core::TensorView tv;
        tv.dtype = va::core::DType::F32;
        if (agg_on_gpu) {
            tv.on_gpu = true;
            tv.data = d_feats_base;
            tv.shape = { N, static_cast<int64_t>(feat_dim) };
        } else {
            tv.on_gpu = false;
            tv.data = roi_seq_feat_buf_.data();
            tv.shape = { static_cast<int64_t>(roi_seq_feat_buf_.size() / static_cast<size_t>(feat_dim)),
                         static_cast<int64_t>(feat_dim) };
        }
        outs.clear();
        outs.push_back(tv);
    } else {
        // 普通路径：单次调用 session_->run 处理完整 batch
        if (!session_ || !session_->run(it->second, outs)) {
            infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
            return false;
        }
    }

    if (outs.empty()) {
        infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
        VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
            << "model.run produced zero outputs (path='" << model_path_ << "').";
        return false;
    }
    // Map outputs to keys (support multiple outputs and auto keys)
    if (!outs.empty()) {
        const size_t n_model = outs.size();
        const size_t n_keys  = out_keys_.size();
        // Try to use real model output names when not provided in YAML
        std::vector<std::string> model_out_names;
        try { if (session_) model_out_names = session_->outputNames(); } catch (...) { /* ignore */ }
        // 详细日志：列出前若干输出 shape 与 on_gpu 标志
        try {
            std::string shapes;
            for (size_t i=0;i<n_model && i<3;i++) {
                auto& t = outs[i];
                std::string s; for (size_t k=0;k<t.shape.size();++k){ s += (k?"x":""); s += std::to_string(t.shape[k]); }
                if (i) shapes += ","; shapes += s; shapes += (t.on_gpu?"(gpu)":"(cpu)");
            }
            VA_LOG_THROTTLED(::va::core::LogLevel::Info, "ms.node_model", 1000)
                << "out_count=" << n_model << " out0..2=" << shapes;
        } catch (...) {}
        auto sanitize = [](std::string s) {
            for (auto& c : s) {
                bool ok = (c == '_') || (c == '-') || (c == ':') ||
                          (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9');
                if (!ok) c = '_';
            }
            return s;
        };
        for (size_t i = 0; i < n_model; ++i) {
            std::string key;
            if (i < n_keys && !out_keys_[i].empty()) {
                key = out_keys_[i];
            } else if (i < model_out_names.size() && !model_out_names[i].empty()) {
                key = std::string("tensor:") + sanitize(model_out_names[i]);
            } else {
                key = std::string("tensor:out") + std::to_string(i);
            }
            p.tensors[key] = outs[i];
            if (i == 0) {
                // Back-compat alias for first output commonly used for detection
                p.tensors["tensor:det_raw"] = outs[i];
            }
        }
    }
    if (!outs.empty()) {
        auto& t = outs.front();
        std::string shape_str;
        for (size_t i=0;i<t.shape.size();++i){ shape_str += (i?"x":""); shape_str += std::to_string(t.shape[i]); }
        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.node_model");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.node_model");
        VA_LOG_THROTTLED(lvl, "ms.node_model", thr)
            << "out_count=" << outs.size() << " out0_shape=" << shape_str << " on_gpu=" << std::boolalpha << t.on_gpu;
    } else {
        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.node_model");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.node_model");
        VA_LOG_THROTTLED(lvl, "ms.node_model", thr) << "out_count=0";
    }
    return true;
}

bool NodeModel::hotSwapModel(const std::string& new_model_path, NodeContext& ctx) {
    if (new_model_path.empty()) return false;
    if (new_model_path == model_path_ && session_) {
        // No-op if same path and session exists
        return true;
    }
    // Close existing by resetting session_
    session_.reset();
    model_path_ = new_model_path;
    return open(ctx);
}

} } } // namespace
