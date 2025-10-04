#include "analyzer/cuda/renderer_overlay_cuda.hpp"

#include "core/utils.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <string>
#include <vector>

#if defined(USE_CUDA)
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_OVERLAY_HAS_CUDA 1
#    else
#      define VA_OVERLAY_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_OVERLAY_HAS_CUDA 1
#  endif
#else
#  define VA_OVERLAY_HAS_CUDA 0
#endif

#if VA_OVERLAY_HAS_CUDA
namespace va::analyzer::cuda {
bool launchDrawBoxes(unsigned char* frame,
                     int width,
                     int height,
                     int pitch,
                     const DeviceDetection* detections,
                     int count,
                     float alpha,
                     int border);

bool launchDrawLabels(unsigned char* frame,
                      int width,
                      int height,
                      int pitch,
                      const DeviceLabel* labels,
                      int count,
                      const char* text_buffer,
                      int text_bytes,
                      float alpha);
}
#endif

namespace {
#if VA_OVERLAY_HAS_CUDA
struct CudaDeleter {
    void operator()(void* ptr) const noexcept {
        if (ptr) {
            cudaFree(ptr);
        }
    }
};

std::array<unsigned char, 3> makeColor(int cls) {
    std::uint32_t seed = static_cast<std::uint32_t>(cls) * 1664525u + 1013904223u;
    unsigned char b = static_cast<unsigned char>(seed & 0xFFu);
    unsigned char g = static_cast<unsigned char>((seed >> 8) & 0xFFu);
    unsigned char r = static_cast<unsigned char>((seed >> 16) & 0xFFu);
    if (r == 0 && g == 0 && b == 0) {
        r = 255;
    }
    return {b, g, r};
}

constexpr int kFontWidth = 5;
constexpr int kFontHeight = 7;
constexpr int kFontSpacing = 1;
constexpr int kLabelPadX = 4;
constexpr int kLabelPadY = 3;
constexpr float kLabelAlpha = 0.65f;
constexpr int kBorderThicknessMin = 1;
#endif
} // namespace

namespace va::analyzer::cuda {

bool OverlayRendererCUDA::draw(const core::Frame& in,
                               const core::ModelOutput& output,
                               core::Frame& out) {
    (void)output;
    out = in;
    return true;
}

bool OverlayRendererCUDA::draw(const core::FrameSurface& in,
                               const core::ModelOutput& output,
                               core::FrameSurface& out) {
    if (drawGpu(in, output, out)) {
        return true;
    }

    core::Frame frame;
    if (!core::surfaceToFrame(in, frame)) {
        return false;
    }
    draw(frame, output, frame);
    out = core::makeSurfaceFromFrame(frame);
    return true;
}

bool OverlayRendererCUDA::drawGpu(const core::FrameSurface& in,
                                  const core::ModelOutput& output,
                                  core::FrameSurface& out) {
#if !VA_OVERLAY_HAS_CUDA
    (void)in;
    (void)output;
    (void)out;
    return false;
#else
    if (in.width <= 0 || in.height <= 0) {
        return false;
    }

    core::FrameSurface working = in;
    bool used_external_surface = true;

    unsigned char* device_ptr = nullptr;
    std::size_t pitch = 0;

    if (in.handle.device_ptr && in.handle.format == core::PixelFormat::BGR24) {
        device_ptr = static_cast<unsigned char*>(in.handle.device_ptr);
        pitch = in.handle.pitch > 0 ? in.handle.pitch : static_cast<std::size_t>(in.width) * 3ull;
    } else {
        core::Frame frame;
        if (!core::surfaceToFrame(in, frame)) {
            return false;
        }
        if (!copyFrameToDevice(frame, working)) {
            return false;
        }
        device_ptr = static_cast<unsigned char*>(working.handle.device_ptr);
        pitch = working.handle.pitch;
        used_external_surface = false;
    }

    if (!device_ptr || pitch == 0) {
        return false;
    }

    host_detections_.clear();
    host_detections_.reserve(output.boxes.size());
    host_labels_.clear();
    host_labels_.reserve(output.boxes.size());
    host_label_text_.clear();

    const int max_w = working.width;
    const int max_h = working.height;

    for (const auto& box : output.boxes) {
        if (box.x2 <= box.x1 || box.y2 <= box.y1) {
            continue;
        }

        int x1 = static_cast<int>(std::floor(box.x1));
        int y1 = static_cast<int>(std::floor(box.y1));
        int x2 = static_cast<int>(std::ceil(box.x2));
        int y2 = static_cast<int>(std::ceil(box.y2));

        x1 = std::clamp(x1, 0, std::max(0, max_w - 1));
        y1 = std::clamp(y1, 0, std::max(0, max_h - 1));
        x2 = std::clamp(x2, 0, std::max(0, max_w - 1));
        y2 = std::clamp(y2, 0, std::max(0, max_h - 1));

        if (x2 <= x1 || y2 <= y1) {
            continue;
        }

        auto color = makeColor(box.cls);
        DeviceDetection detection;
        detection.x1 = x1;
        detection.y1 = y1;
        detection.x2 = x2;
        detection.y2 = y2;
        detection.b = color[0];
        detection.g = color[1];
        detection.r = color[2];
        host_detections_.push_back(detection);

        char text_buffer[64];
        int score_pct = static_cast<int>(std::round(box.score * 100.0f));
        score_pct = std::clamp(score_pct, 0, 100);
        std::snprintf(text_buffer, sizeof(text_buffer), "CLS %d | %d%%", box.cls, score_pct);
        const std::string label_text = text_buffer;
        if (label_text.empty()) {
            continue;
        }

        const int text_len = static_cast<int>(label_text.size());
        const int glyph_width = text_len * (kFontWidth + kFontSpacing) - kFontSpacing;
        const int label_width = glyph_width + kLabelPadX * 2;
        const int label_height = kFontHeight + kLabelPadY * 2;

        int label_x = x1;
        if (label_x + label_width > max_w) {
            label_x = std::max(0, max_w - label_width);
        }

        int label_y = y1 - label_height - 2;
        if (label_y < 0) {
            label_y = std::min(max_h - label_height, y2 + 2);
            label_y = std::max(0, label_y);
        }

        DeviceLabel label;
        label.x = label_x;
        label.y = label_y;
        label.width = label_width;
        label.height = label_height;
        label.text_offset = static_cast<int>(host_label_text_.size());
        label.text_length = text_len;
        label.r = detection.r;
        label.g = detection.g;
        label.b = detection.b;

        host_label_text_.append(label_text);
        host_labels_.push_back(label);
    }

    if (!host_detections_.empty()) {
        const std::size_t bytes = host_detections_.size() * sizeof(DeviceDetection);
        if (!ensureBuffer(detection_buffer_, bytes)) {
            return false;
        }
        if (cudaMemcpy(detection_buffer_.ptr.get(),
                       host_detections_.data(),
                       bytes,
                       cudaMemcpyHostToDevice) != cudaSuccess) {
            return false;
        }

        const int pitch_int = static_cast<int>(pitch);
        const int border = std::max(border_thickness_, kBorderThicknessMin);
        if (!launchDrawBoxes(device_ptr,
                             working.width,
                             working.height,
                             pitch_int,
                             static_cast<DeviceDetection*>(detection_buffer_.ptr.get()),
                             static_cast<int>(host_detections_.size()),
                             overlay_alpha_,
                             border)) {
            return false;
        }
    }

    if (!host_labels_.empty() && !host_label_text_.empty()) {
        const std::size_t label_bytes = host_labels_.size() * sizeof(DeviceLabel);
        if (!ensureBuffer(label_buffer_, label_bytes)) {
            return false;
        }
        if (cudaMemcpy(label_buffer_.ptr.get(),
                       host_labels_.data(),
                       label_bytes,
                       cudaMemcpyHostToDevice) != cudaSuccess) {
            return false;
        }

        const std::size_t text_bytes = host_label_text_.size();
        if (!ensureBuffer(label_text_buffer_, text_bytes)) {
            return false;
        }
        if (cudaMemcpy(label_text_buffer_.ptr.get(),
                       host_label_text_.data(),
                       text_bytes,
                       cudaMemcpyHostToDevice) != cudaSuccess) {
            return false;
        }

        const int pitch_int = static_cast<int>(pitch);
        if (!launchDrawLabels(device_ptr,
                              working.width,
                              working.height,
                              pitch_int,
                              static_cast<DeviceLabel*>(label_buffer_.ptr.get()),
                              static_cast<int>(host_labels_.size()),
                              static_cast<const char*>(label_text_buffer_.ptr.get()),
                              static_cast<int>(host_label_text_.size()),
                              kLabelAlpha)) {
            return false;
        }
    }

    if (!used_external_surface) {
        out = working;
    } else {
        out = in;
        out.handle.device_ptr = device_ptr;
        out.handle.bytes = working.handle.bytes;
        out.handle.pitch = pitch;
        out.handle.location = core::MemoryLocation::Device;
        out.handle.format = core::PixelFormat::BGR24;
    }

    return true;
#endif
}

bool OverlayRendererCUDA::ensureBuffer(DeviceBuffer& buffer, std::size_t bytes) {
#if !VA_OVERLAY_HAS_CUDA
    (void)buffer;
    (void)bytes;
    return false;
#else
    if (bytes == 0) {
        return false;
    }
    if (!buffer.ptr || buffer.capacity < bytes) {
        void* ptr = nullptr;
        if (cudaMalloc(&ptr, bytes) != cudaSuccess) {
            buffer.ptr.reset();
            buffer.capacity = 0;
            return false;
        }
        buffer.ptr.reset(ptr, CudaDeleter{});
        buffer.capacity = bytes;
    }
    return true;
#endif
}

bool OverlayRendererCUDA::copyFrameToDevice(const core::Frame& frame,
                                            core::FrameSurface& out) {
#if !VA_OVERLAY_HAS_CUDA
    (void)frame;
    (void)out;
    return false;
#else
    const int width = frame.width;
    const int height = frame.height;
    if (width <= 0 || height <= 0 || frame.bgr.empty()) {
        return false;
    }
    const std::size_t bytes = static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 3ull;
    if (!ensureBuffer(device_buffer_, bytes)) {
        return false;
    }
    if (cudaMemcpy(device_buffer_.ptr.get(),
                   frame.bgr.data(),
                   bytes,
                   cudaMemcpyHostToDevice) != cudaSuccess) {
        return false;
    }

    out.width = width;
    out.height = height;
    out.pts_ms = frame.pts_ms;
    out.handle.device_ptr = device_buffer_.ptr.get();
    out.handle.device_owner = device_buffer_.ptr;
    out.handle.bytes = bytes;
    out.handle.pitch = static_cast<std::size_t>(width) * 3ull;
    out.handle.width = width;
    out.handle.height = height;
    out.handle.location = core::MemoryLocation::Device;
    out.handle.format = core::PixelFormat::BGR24;
    out.handle.host_ptr = nullptr;
    out.handle.host_owner.reset();
    return true;
#endif
}

} // namespace va::analyzer::cuda
