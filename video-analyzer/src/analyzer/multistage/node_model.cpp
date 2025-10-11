#include "analyzer/multistage/node_model.hpp"
#include "analyzer/ort_session.hpp"
#include "core/engine_manager.hpp"
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
    }
    session_ = std::move(s);
    return true;
}

bool NodeModel::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    std::vector<va::core::TensorView> outs;
    if (!session_ || !session_->run(it->second, outs)) return false;
    // Map outputs to keys (support multiple outputs if provided)
    if (!out_keys_.empty()) {
        const size_t n = std::min(out_keys_.size(), outs.size());
        for (size_t i = 0; i < n; ++i) {
            p.tensors[out_keys_[i]] = outs[i];
        }
        // If keys provided but outs fewer, leave missing keys untouched
    } else if (!outs.empty()) {
        // No keys provided: export the first output under a default key
        p.tensors["tensor:det_raw"] = outs[0];
    }
    if (!outs.empty()) {
        auto& t = outs.front();
        std::string shape_str;
        for (size_t i=0;i<t.shape.size();++i){ shape_str += (i?"x":""); shape_str += std::to_string(t.shape[i]); }
        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ms.node_model", 1000)
            << "out_count=" << outs.size() << " out0_shape=" << shape_str << " on_gpu=" << std::boolalpha << t.on_gpu;
    } else {
        VA_LOG_THROTTLED(::va::core::LogLevel::Debug, "ms.node_model", 1000) << "out_count=0";
    }
    return true;
}

} } } // namespace
