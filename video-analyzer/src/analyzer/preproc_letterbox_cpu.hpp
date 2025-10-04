#pragma once

#include "analyzer/interfaces.hpp"

#include <opencv2/core/mat.hpp>
#include <vector>

namespace va::analyzer {

class LetterboxPreprocessorCPU : public IPreprocessor {
public:
    LetterboxPreprocessorCPU(int input_width, int input_height);

    bool run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) override;
    bool run(const core::FrameSurface& in,
             core::TensorView& out,
             core::LetterboxMeta& meta) override;

private:
    bool runImpl(const cv::Mat& src,
                 int width,
                 int height,
                 double pts_ms,
                 core::TensorView& out,
                 core::LetterboxMeta& meta);

    int input_width_;
    int input_height_;
    std::vector<float> buffer_;
};

} // namespace va::analyzer
