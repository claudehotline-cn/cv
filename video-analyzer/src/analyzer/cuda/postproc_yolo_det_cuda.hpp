#pragma once

#include "core/utils.hpp"

#include <memory>
#include <vector>

namespace va::analyzer::cuda {

class YoloPostprocessorCUDA {
public:
    bool decode(const core::TensorView& tensor,
                const core::LetterboxMeta& meta,
                std::vector<core::Box>& boxes);

private:
    struct DeviceBuffer {
        std::shared_ptr<void> ptr;
        std::size_t capacity {0};
    };

    bool ensureBuffer(DeviceBuffer& buffer, std::size_t bytes);

    DeviceBuffer boxes_buffer_;
    DeviceBuffer counter_buffer_;
};

struct DeviceBox {
    float x1;
    float y1;
    float x2;
    float y2;
    float score;
    int cls;
    int suppressed;
};

bool launchYoloNms(DeviceBox* boxes, int count, float iou_threshold);

} // namespace va::analyzer::cuda
