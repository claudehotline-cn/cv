#pragma once

#include "analyzer/interfaces.hpp"
#include "analyzer/preproc_letterbox_cpu.hpp"

#include <memory>

namespace va::analyzer {

class LetterboxPreprocessorCUDA : public IPreprocessor {
public:
    LetterboxPreprocessorCUDA(int input_width, int input_height);

    bool run(const core::Frame& in, core::TensorView& out, core::LetterboxMeta& meta) override;
    bool run(const core::FrameSurface& in,
             core::TensorView& out,
             core::LetterboxMeta& meta) override;

private:
    struct DeviceBuffer {
        std::shared_ptr<void> ptr;
        std::size_t capacity {0};
    };

    bool runGpu(const core::FrameSurface& in, core::TensorView& out, core::LetterboxMeta& meta);
    bool ensureBuffer(DeviceBuffer& buffer, std::size_t bytes);

    int input_width_;
    int input_height_;
    LetterboxPreprocessorCPU cpu_fallback_;
    DeviceBuffer rgb_buffer_;
    DeviceBuffer tensor_buffer_;
};

} // namespace va::analyzer
