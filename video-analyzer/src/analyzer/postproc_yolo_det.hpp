#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>

namespace va::analyzer {

#if defined(USE_CUDA)
namespace cuda {
class YoloPostprocessorCUDA;
}
#endif

class YoloDetectionPostprocessor : public IPostprocessor {
public:
    YoloDetectionPostprocessor();
    ~YoloDetectionPostprocessor() override;

    bool run(const std::vector<core::TensorView>& raw_outputs,
             const core::LetterboxMeta& meta,
             core::ModelOutput& output) override;

private:
#if defined(USE_CUDA)
    std::unique_ptr<cuda::YoloPostprocessorCUDA> gpu_impl_;
#endif
};

} // namespace va::analyzer
