#include "analyzer/multistage/node_preproc_letterbox.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"
#include "analyzer/preproc_letterbox_cuda.hpp"

using va::analyzer::multistage::util::get_or_int;

namespace va { namespace analyzer { namespace multistage {

NodePreprocLetterbox::NodePreprocLetterbox(const std::unordered_map<std::string,std::string>& cfg) {
    out_h_ = get_or_int(cfg, "out_h", 640);
    out_w_ = get_or_int(cfg, "out_w", 640);
    prefer_cuda_ = get_or_int(cfg, "use_cuda", 1) != 0;
}

bool NodePreprocLetterbox::process(Packet& p, NodeContext& ctx) {
    // Choose CUDA when possible; fallback to CPU
    va::core::TensorView t;
    va::core::LetterboxMeta meta;
#ifdef USE_CUDA
    if (prefer_cuda_) {
        static std::unique_ptr<va::analyzer::LetterboxPreprocessorCUDA> pre;
        if (!pre) pre = std::make_unique<va::analyzer::LetterboxPreprocessorCUDA>(out_w_, out_h_);
        pre->setStream(ctx.stream);
        if (!pre->run(p.frame, t, meta)) { return false; }
        p.letterbox = meta;
        p.tensors["tensor:det_input"] = t;
        return true;
    }
#endif
    static std::unique_ptr<va::analyzer::LetterboxPreprocessorCPU> pre_cpu;
    if (!pre_cpu) pre_cpu = std::make_unique<va::analyzer::LetterboxPreprocessorCPU>(out_w_, out_h_);
    if (!pre_cpu->run(p.frame, t, meta)) { return false; }
    p.letterbox = meta;
    p.tensors["tensor:det_input"] = t;
    return true;
}

} } } // namespace
