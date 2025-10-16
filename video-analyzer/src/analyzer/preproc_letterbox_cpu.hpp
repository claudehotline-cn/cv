#pragma once

#include "analyzer/interfaces.hpp"

#include <vector>

namespace va::analyzer {

class LetterboxPreprocessorCPU : public IPreprocessor {
public:
    LetterboxPreprocessorCPU(int input_width, int input_height);

    bool run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) override;

private:
    int input_width_;
    int input_height_;
    std::vector<float> buffer_;
};

} // namespace va::analyzer
