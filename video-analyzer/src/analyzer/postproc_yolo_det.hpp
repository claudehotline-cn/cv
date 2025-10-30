#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class YoloDetectionPostprocessor : public IPostprocessor {
public:
    bool run(const std::vector<core::TensorView>& raw_outputs,
             const core::LetterboxMeta& meta,
             core::ModelOutput& output) override;
};

#ifdef USE_CUDA
class YoloDetectionPostprocessorCUDA : public IPostprocessor {
public:
    void setStream(void* s) { stream_ = s; }
    bool run(const std::vector<core::TensorView>& raw_outputs,
             const core::LetterboxMeta& meta,
             core::ModelOutput& output) override;
private:
    void* stream_ {nullptr};
};
#endif

} // namespace va::analyzer
