#pragma once

#include "analyzer/interfaces.hpp"

namespace va::analyzer {

class LetterboxPreprocessorCUDA : public IPreprocessor {
public:
    LetterboxPreprocessorCUDA(int input_width, int input_height);
    ~LetterboxPreprocessorCUDA() override;

    bool run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) override;

private:
    bool ensureDeviceCapacity(std::size_t bytes);
    void releaseDevice();

    int input_width_;
    int input_height_;

    void* device_ptr_ {nullptr};
    std::size_t capacity_bytes_ {0};
};

} // namespace va::analyzer
