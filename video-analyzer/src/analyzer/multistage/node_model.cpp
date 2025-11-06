#include "analyzer/multistage/node_model.hpp"
#include "analyzer/model_session_factory.hpp"
#include "core/engine_manager.hpp"
#include "analyzer/logging_util.hpp"
#include <algorithm>
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"

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
}

bool NodeModel::open(NodeContext& ctx) {
    if (session_) return true;

    // Create model session via factory (encapsulates provider priority and options mapping)
    va::core::EngineDescriptor desc;
    if (ctx.engine_registry) {
        try { desc = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry)->currentEngine(); }
        catch (...) { /* ignore */ }
    }

    ProviderDecision dec{};
    auto s = va::analyzer::create_model_session(desc, ctx, &dec);

    // 根据 provider 选择实际模型路径：tensorrt-native -> 优先 model_path_trt_；否则优先 model_path_ort_
    std::string chosen_path = model_path_;
    try {
        std::string prov = dec.resolved;
        std::transform(prov.begin(), prov.end(), prov.begin(), [](unsigned char c){ return (char)std::tolower(c); });
        if ((prov == "tensorrt-native" || prov == "tensorrt_native" || prov == "trt-native") && !model_path_trt_.empty()) {
            chosen_path = model_path_trt_;
        } else if (!model_path_ort_.empty()) {
            chosen_path = model_path_ort_;
        }
    } catch (...) { /* keep default */ }

    if (!chosen_path.empty()) {
        VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model")
            << "open: model_path='" << chosen_path << "' provider_req='" << dec.requested
            << "' device_id=" << desc.device_index;
        if (!s->loadModel(chosen_path, /*use_gpu*/false)) {
            VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model") << "failed to load model: " << chosen_path;
            return false;
        }
        // 若模型未声明任何输出，直接判定为配置/工件错误，避免下游误报 NMS 失败
        try {
            auto out_names_probe = s->outputNames();
            if (out_names_probe.empty()) {
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model")
                    << "model has zero declared outputs (path='" << model_path_ << "'). Check ONNX graph outputs / export config (nms=False).";
                return false;
            }
        } catch (...) { /* ignore */ }

        // 回填 EngineManager 的运行态（provider/gpu/io_binding/device_binding），用于 RuntimeSummary
        if (ctx.engine_registry) {
            try {
                auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
                auto ri = s->getRuntimeInfo();
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
            auto names = s->outputNames();
            VA_LOG_C(::va::core::LogLevel::Info, "ms.node_model") << "outputs_declared=" << names.size();
        } catch (...) {}
    }
    session_ = std::move(s);
    return true;
}

bool NodeModel::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    // 移除冗余推理输入日志，避免控制台噪声
    std::vector<va::core::TensorView> outs;
    if (!session_ || !session_->run(it->second, outs)) {
        infer_fail_count_.fetch_add(1, std::memory_order_relaxed);
        return false;
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
