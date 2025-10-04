#pragma once

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <vector>
#include <string>
#include <vector>
#include <memory>
#include <functional>

namespace va::core {

// New: generic memory location for buffers
enum class MemoryLocation {
    Host,
    Device
};

// New: minimal pixel/element format tags for surfaces/tensors
enum class PixelFormat {
    Unknown,
    NV12,
    P010,
    BGR24,
    RGB8,
    RGBA32F
};

enum class DType {
    U8,
    F32,
    F16
};

// New: unified handle for host/device buffers
struct MemoryHandle {
    void* host_ptr {nullptr};
    void* device_ptr {nullptr};
    std::size_t bytes {0};
    std::size_t pitch {0};
    int width {0};
    int height {0};
    void* stream {nullptr}; // optional CUDA stream pointer when available
    MemoryLocation location {MemoryLocation::Host};
    PixelFormat format {PixelFormat::Unknown};
    std::shared_ptr<void> host_owner;
    std::shared_ptr<void> device_owner;

    bool ensureHost();
    bool ensureDevice();
};

// New: GPU/CPU-agnostic video frame surface
struct FrameSurface {
    MemoryHandle handle;
    double pts_ms {0.0};
    int width {0};
    int height {0};
};

struct Frame {
    int width {0};
   int height {0};
   double pts_ms {0.0};
   std::vector<uint8_t> bgr;
   FrameSurface surface;
   bool has_surface {false};
    std::function<void(MemoryHandle&&)> surface_recycle;
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
    void* device_data {nullptr};
    std::vector<int64_t> shape;
    DType dtype {DType::F32};
    std::size_t bytes {0};
    bool on_gpu {false};
    // Optional new handle for future GPU-first processing
    MemoryHandle handle;
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

// Helpers to bridge Frame ↔ FrameSurface while keeping ownership rules explicit.
FrameSurface makeSurfaceFromFrame(const Frame& frame);
bool surfaceToFrame(const FrameSurface& surface, Frame& out);
bool surfaceHasData(const FrameSurface& surface);

inline double ms_now() {
    using clock = std::chrono::steady_clock;
    return std::chrono::duration<double, std::milli>(clock::now().time_since_epoch()).count();
}

} // namespace va::core

