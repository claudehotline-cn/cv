#pragma once

#include <cstdint>
#include <chrono>
#include <string>
#include <vector>

namespace va::core {

enum class DType {
    U8,
    F32,
    F16
};

enum class PixelFormat {
    UNKNOWN,
    BGR24,
    RGB24,
    NV12,
    YUV420P
};

struct DeviceSurface {
    void* data0 {nullptr};
    void* data1 {nullptr};
    int pitch0 {0};
    int pitch1 {0};
    int width {0};
    int height {0};
    PixelFormat fmt {PixelFormat::UNKNOWN};
    bool on_gpu {false};
};

struct Frame {
    int width {0};
    int height {0};
    double pts_ms {0.0};
    std::vector<uint8_t> bgr;
    // Optional device surface metadata (experimental)
    bool has_device_surface {false};
    DeviceSurface device;
};

struct LetterboxMeta {
    float scale {1.0f};
    int pad_x {0};
    int pad_y {0};
    int input_width {0};
    int input_height {0};
    int original_width {0};
    int original_height {0};
};

struct TensorView {
    void* data {nullptr};
    std::vector<int64_t> shape;
    DType dtype {DType::F32};
    bool on_gpu {false};
};

struct Box {
    float x1 {0.0f};
    float y1 {0.0f};
    float x2 {0.0f};
    float y2 {0.0f};
    float score {0.0f};
    int cls {0};
};

struct ModelOutput {
    std::vector<Box> boxes;
    std::vector<std::vector<uint8_t>> masks;
};

inline double ms_now() {
    using clock = std::chrono::steady_clock;
    return std::chrono::duration<double, std::milli>(clock::now().time_since_epoch()).count();
}

} // namespace va::core

