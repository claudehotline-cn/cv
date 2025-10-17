#include "analyzer/multistage/node_model.hpp"
#include "analyzer/ort_session.hpp"
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
}

bool NodeModel::open(NodeContext& ctx) {
    if (session_) return true;
    auto s = std::make_shared<va::analyzer::OrtModelSession>();

#ifdef USE_ONNXRUNTIME
    // Infer provider/device from EngineManager if available
    va::analyzer::OrtModelSession::Options opt;
    bool prefer_gpu = false;
    int device_id = 0;
    bool stage_device_outputs = false;
    bool device_output_views = false;
    if (ctx.engine_registry) {
        try {
            auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
            auto desc = em->currentEngine();
            std::string prov = desc.provider; 
            std::transform(prov.begin(), prov.end(), prov.begin(), [](unsigned char c){ return (char)std::tolower(c); });
            if (prov.find("cuda") != std::string::npos || prov.find("trt") != std::string::npos) {
                prefer_gpu = true;
                opt.provider = "cuda"; // normalize to CUDA EP here; TRT can be added later when needed
            } else {
                opt.provider = "cpu";
            }
            device_id = desc.device_index;
            // Read optional IoBinding output preferences from engine options map
            auto findBool = [&](const char* key, bool defv){
                auto it = desc.options.find(key);
                if (it == desc.options.end()) return defv;
                std::string v = it->second; std::transform(v.begin(), v.end(), v.begin(), [](unsigned char c){return (char)std::tolower(c);} );
                if (v=="1"||v=="true"||v=="yes"||v=="on") return true;
                if (v=="0"||v=="false"||v=="no"||v=="off") return false;
                return defv;
            };
            stage_device_outputs = findBool("stage_device_outputs", false);
            device_output_views = findBool("device_output_views", false);
        } catch (...) {
            opt.provider = prefer_gpu ? std::string("cuda") : std::string("cpu");
        }
    } else {
        opt.provider = "cpu";
    }
    opt.device_id = device_id;
    opt.use_io_binding = prefer_gpu;           // enable IoBinding for device input/output
    opt.prefer_pinned_memory = prefer_gpu;     // prefer pinned when staging
    opt.allow_cpu_fallback = true;
    opt.stage_device_outputs = stage_device_outputs;
    opt.device_output_views = device_output_views;
    s->setOptions(opt);
#endif

    if (!model_path_.empty()) {
        if (!s->loadModel(model_path_, /*use_gpu*/false /*opt controls EP*/)) {
            VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model") << "failed to load model: " << model_path_;
            return false;
        }
        // 回填 EngineManager 的运行态（provider/gpu/io_binding/device_binding），用于 RuntimeSummary
        if (ctx.engine_registry) {
            try {
                auto* em = reinterpret_cast<va::core::EngineManager*>(ctx.engine_registry);
                auto ri = s->runtimeInfo();
                va::core::EngineRuntimeStatus st;
                st.provider = ri.provider;
                st.gpu_active = ri.gpu_active;
                st.io_binding = ri.io_binding_active;
                st.device_binding = ri.device_binding_active;
                st.cpu_fallback = ri.cpu_fallback;
                em->updateRuntimeStatus(std::move(st));
                VA_LOG_C(::va::core::LogLevel::Info, "app") << "[RuntimeSummary][post-open] provider=" << ri.provider
                    << " gpu_active=" << std::boolalpha << ri.gpu_active
                    << " io_binding=" << ri.io_binding_active
                    << " device_binding=" << ri.device_binding_active;
            } catch (...) { /* best-effort */ }
        }
    }
    session_ = std::move(s);
    return true;
}

bool NodeModel::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    std::vector<va::core::TensorView> outs;
    if (!session_ || !session_->run(it->second, outs)) return false;
    // Map outputs to keys (support multiple outputs and auto keys)
    if (!outs.empty()) {
        const size_t n_model = outs.size();
        const size_t n_keys  = out_keys_.size();
        // Try to use real model output names when not provided in YAML
        std::vector<std::string> model_out_names;
        try {
            if (session_) {
                if (auto ort = std::dynamic_pointer_cast<va::analyzer::OrtModelSession>(session_)) {
                    model_out_names = ort->outputNames();
                }
            }
        } catch (...) { /* ignore */ }
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
