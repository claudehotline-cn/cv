#pragma once

#include "analyzer/interfaces.hpp"

#include <memory>
#include <string>
#include <vector>

namespace va::analyzer::cuda {

struct DeviceDetection {
    int x1;
    int y1;
    int x2;
    int y2;
    unsigned char r;
    unsigned char g;
    unsigned char b;
};

struct DeviceLabel {
    int x;
    int y;
    int width;
    int height;
    int text_offset;
    int text_length;
    unsigned char r;
    unsigned char g;
    unsigned char b;
};

class OverlayRendererCUDA : public IRenderer {
public:
    bool draw(const core::Frame& in, const core::ModelOutput& output, core::Frame& out) override;
    bool draw(const core::FrameSurface& in,
              const core::ModelOutput& output,
              core::FrameSurface& out) override;

private:
    struct DeviceBuffer {
        std::shared_ptr<void> ptr;
        std::size_t capacity {0};
    };

    bool drawGpu(const core::FrameSurface& in,
                 const core::ModelOutput& output,
                 core::FrameSurface& out);
    bool ensureBuffer(DeviceBuffer& buffer, std::size_t bytes);
    bool copyFrameToDevice(const core::Frame& frame, core::FrameSurface& out);

    DeviceBuffer device_buffer_;
    DeviceBuffer detection_buffer_;
    DeviceBuffer label_buffer_;
    DeviceBuffer label_text_buffer_;
    std::vector<DeviceDetection> host_detections_;
    std::vector<DeviceLabel> host_labels_;
    std::string host_label_text_;
    float overlay_alpha_ {0.35f};
    int border_thickness_ {2};
};

} // namespace va::analyzer::cuda
