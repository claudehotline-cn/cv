#include "analyzer/model_session_factory.hpp"
#include "analyzer/ort_session.hpp"
#if defined(USE_TENSORRT)
#include "analyzer/trt_session.hpp"
#endif
#include "core/logger.hpp"

#include <algorithm>

namespace va::analyzer {

namespace {
inline std::string to_lower(std::string s) {
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c){ return (char)std::tolower(c); });
    return s;
}

inline bool parse_bool(const std::unordered_map<std::string,std::string>& m,
                       const char* key, bool defv) {
    auto it = m.find(key);
    if (it == m.end()) return defv;
    auto v = to_lower(it->second);
    if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
    if (v=="0"||v=="false"||v=="no"||v=="off") return false;
    return defv;
}

inline int parse_int(const std::unordered_map<std::string,std::string>& m,
                     const char* key, int defv) {
    auto it = m.find(key);
    if (it == m.end()) return defv;
    try { return std::stoi(it->second); } catch (...) { return defv; }
}
}

std::shared_ptr<IModelSession>
create_model_session(const va::core::EngineDescriptor& engine,
                     const va::analyzer::multistage::NodeContext& ctx,
                     ProviderDecision* decision) {
    std::string req = engine.provider.empty() ? engine.name : engine.provider;
    req = to_lower(req);

    // Normalize common aliases
    if (req == "gpu" || req == "ort-gpu" || req == "ort-cuda") req = "cuda";
    if (req == "ort-trt" || req == "ort-tensorrt" || req == "tensor_rt") req = "tensorrt";
    if (req == "triton-grpc" || req == "triton_infer" || req == "tritonserver") req = "triton";
    // 当前不实现 RTX EP：将 RTX 请求视为常规 TensorRT
    if (req == "nv_tensorrt_rtx" || req == "rtx" || req == "tensorrt_rtx") req = "tensorrt";

    // Decide fallback chain (includes tensorrt-native)
    std::string chosen = req;
    if (req != "tensorrt-native" && req != "tensorrt" && req != "cuda" && req != "cpu" && req != "triton") {
        // Unknown provider → prefer GPU if name contains cuda/trt, otherwise cpu
        if (req.find("trt") != std::string::npos || req.find("cuda") != std::string::npos)
            chosen = "cuda";
        else
            chosen = "cpu";
    }

    if (decision) {
        decision->requested = req;
        decision->resolved = chosen; // may be updated below (e.g., Triton fallback)
    }

    // tensorrt-native path (prefer when available and explicitly requested)
#if defined(USE_TENSORRT)
    if (chosen == "tensorrt-native") {
        auto trt = std::make_shared<va::analyzer::TensorRTModelSession>();
        TensorRTModelSession::Options topt;
        topt.device_id = engine.device_index;
        topt.user_stream = ctx.stream;
        const auto& opts = engine.options;
        topt.fp16 = parse_bool(opts, "trt_fp16", false) || parse_bool(opts, "tensorrt_fp16", false);
        topt.workspace_mb = parse_int(opts, "trt_workspace_mb", 0);
        if (topt.workspace_mb <= 0) topt.workspace_mb = parse_int(opts, "tensorrt_workspace_mb", 0);
        topt.device_output_views = parse_bool(opts, "device_output_views", true);
        topt.stage_device_outputs = parse_bool(opts, "stage_device_outputs", false);
        // Optional engine serialization
        topt.serialize_on_build = parse_bool(opts, "trt_serialize_on_build", false) || parse_bool(opts, "serialize_on_build", false);
        if (auto it = opts.find("trt_engine_dir"); it != opts.end()) topt.engine_out_dir = it->second;
        trt->setOptions(topt);
        return trt;
    }
#endif

    // Triton gRPC path (best-effort when enabled)
    if (chosen == "triton") {
#if defined(USE_TRITON_CLIENT)
        va::analyzer::TritonGrpcModelSession::Options topt;
        const auto& opts = engine.options;
        if (auto it = opts.find("triton_url"); it != opts.end()) topt.url = it->second;
        if (auto it = opts.find("triton_model"); it != opts.end()) topt.model_name = it->second;
        if (auto it = opts.find("triton_model_version"); it != opts.end()) topt.model_version = it->second;
        if (auto it = opts.find("triton_input"); it != opts.end()) topt.input_name = it->second;
        if (auto it = opts.find("triton_outputs"); it != opts.end()) {
            topt.output_names.clear();
            std::string v = it->second; std::string cur; for (char c : v){ if (c==','||c==';'){ if(!cur.empty()){ topt.output_names.push_back(cur); cur.clear(); } } else cur.push_back(c);} if(!cur.empty()) topt.output_names.push_back(cur);
        }
        topt.timeout_ms = parse_int(opts, "triton_timeout_ms", 2000);
        topt.use_cuda_shm = parse_bool(opts, "triton_shm_cuda", false);
        topt.cuda_shm_bytes = parse_int(opts, "triton_cuda_shm_bytes", 0);
        topt.device_id = engine.device_index;
        auto s = std::make_shared<va::analyzer::TritonGrpcModelSession>(topt);
        if (decision) { decision->resolved = "triton"; }
        return s;
#else
        VA_LOG_C(::va::core::LogLevel::Warn, "analyzer") << "provider='triton' requested but Triton client disabled; falling back to cuda";
        chosen = "cuda";
        if (decision) { decision->resolved = chosen; }
#endif
    }

    // Default: return ONNX Runtime session with mapped provider preference
    auto session = std::make_shared<va::analyzer::OrtModelSession>();
#ifdef USE_ONNXRUNTIME
    va::analyzer::OrtModelSession::Options opt;
    opt.provider = chosen; // tensorrt/cuda/cpu
    opt.device_id = engine.device_index;
    opt.user_stream = ctx.stream;
    const auto& opts = engine.options;
    const bool gpu_like = (chosen=="tensorrt" || chosen=="cuda");
    opt.use_io_binding = parse_bool(opts, "use_io_binding", gpu_like);
    opt.prefer_pinned_memory = gpu_like;
    opt.allow_cpu_fallback = parse_bool(opts, "allow_cpu_fallback", true);
    opt.stage_device_outputs = parse_bool(opts, "stage_device_outputs", false);
    opt.device_output_views = parse_bool(opts, "device_output_views", false);
    opt.tensorrt_fp16 = parse_bool(opts, "trt_fp16", false) || parse_bool(opts, "tensorrt_fp16", false);
    opt.tensorrt_int8 = parse_bool(opts, "trt_int8", false) || parse_bool(opts, "tensorrt_int8", false);
    opt.tensorrt_workspace_mb = parse_int(opts, "trt_workspace_mb", 0);
    if (opt.tensorrt_workspace_mb <= 0) opt.tensorrt_workspace_mb = parse_int(opts, "tensorrt_workspace_mb", 0);
    opt.tensorrt_max_partition_iterations = parse_int(opts, "trt_max_partition_iterations", 0);
    opt.tensorrt_min_subgraph_size = parse_int(opts, "trt_min_subgraph_size", 0);
    // Pass-through dynamic shape profile hints and builder knobs (if provided)
    if (auto it = opts.find("trt_profile_min_shapes"); it != opts.end()) opt.tensorrt_profile_min_shapes = it->second;
    if (auto it = opts.find("trt_profile_opt_shapes"); it != opts.end()) opt.tensorrt_profile_opt_shapes = it->second;
    if (auto it = opts.find("trt_profile_max_shapes"); it != opts.end()) opt.tensorrt_profile_max_shapes = it->second;
    opt.tensorrt_builder_optimization_level = parse_int(opts, "trt_builder_optimization_level", -1);
    opt.tensorrt_force_sequential_build = parse_bool(opts, "trt_force_sequential", false);
    opt.tensorrt_auxiliary_streams = parse_int(opts, "trt_auxiliary_streams", -1);
    opt.tensorrt_detailed_build_log = parse_bool(opts, "trt_detailed_build_log", false);
    // warmup_runs: support "auto" -> -1, "off"/"false"/"0" -> 0, or numeric
    {
        int wu = 1; // default
        auto it = opts.find("warmup_runs");
        if (it != opts.end()) {
            auto v = to_lower(it->second);
            if (v == "auto" || v == "-1") {
                wu = -1;
            } else if (v == "off" || v == "false" || v == "0" || v == "no") {
                wu = 0;
            } else {
                try { wu = std::stoi(v); } catch (...) { wu = 1; }
            }
        }
        opt.warmup_runs = wu;
    }
    // 默认不强制 RTX：仅当 require_rtx=true 时才严格要求
    opt.require_rtx_when_requested = parse_bool(opts, "require_rtx", false);
    session->setOptions(opt);
    if (decision) { decision->resolved = chosen; }
#endif
    return session;
}

} // namespace va::analyzer
