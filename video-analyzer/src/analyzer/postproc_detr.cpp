#include "analyzer/postproc_detr.hpp"

namespace va::analyzer {

bool DetrPostprocessor::run(const std::vector<core::TensorView>& /*raw_outputs*/,
                            const core::LetterboxMeta& /*meta*/,
                            core::ModelOutput& output) {
    output.boxes.clear();
    output.masks.clear();
    return true;
}

} // namespace va::analyzer
