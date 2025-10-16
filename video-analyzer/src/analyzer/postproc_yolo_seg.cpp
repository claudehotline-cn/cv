#include "analyzer/postproc_yolo_seg.hpp"

namespace va::analyzer {

bool YoloSegmentationPostprocessor::run(const std::vector<core::TensorView>& /*raw_outputs*/,
                                        const core::LetterboxMeta& /*meta*/,
                                        core::ModelOutput& output) {
    output.boxes.clear();
    output.masks.clear();
    return true;
}

} // namespace va::analyzer
