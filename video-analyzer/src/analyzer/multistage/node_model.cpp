#include "analyzer/multistage/node_model.hpp"
#include "analyzer/ort_session.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"

using va::analyzer::multistage::util::get_or;

namespace va { namespace analyzer { namespace multistage {

NodeModel::NodeModel(const std::unordered_map<std::string,std::string>& cfg) {
    auto itIn = cfg.find("in"); if (itIn != cfg.end()) in_key_ = itIn->second;
    auto itOuts = cfg.find("outs"); if (itOuts != cfg.end()) { out_keys_.clear(); out_keys_.push_back(itOuts->second); }
    auto itPath = cfg.find("model_path"); if (itPath != cfg.end()) model_path_ = itPath->second;
}

bool NodeModel::open(NodeContext& /*ctx*/) {
    if (!session_) {
        auto s = std::make_shared<va::analyzer::OrtModelSession>();
        if (!model_path_.empty()) {
            // Use GPU when provider contains "cuda/trt" via env/engine; here simply hint false -> session may override.
            if (!s->loadModel(model_path_, /*use_gpu*/false)) {
                VA_LOG_C(::va::core::LogLevel::Error, "ms.node_model") << "failed to load model: " << model_path_;
                return false;
            }
        }
        session_ = std::move(s);
    }
    return true;
}

bool NodeModel::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    std::vector<va::core::TensorView> outs;
    if (!session_ || !session_->run(it->second, outs)) return false;
    // Map outputs to keys (single-output minimal case)
    if (!out_keys_.empty()) {
        if (!outs.empty()) p.tensors[out_keys_[0]] = outs[0];
    }
    return true;
}

} } } // namespace

