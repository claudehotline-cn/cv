#include "analyzer/cuda/renderer_overlay_cuda.hpp"

#include <cuda_runtime.h>

namespace va::analyzer::cuda {

namespace {

__device__ inline unsigned char blendComponent(unsigned char base, unsigned char color, float alpha) {
    return static_cast<unsigned char>(alpha * static_cast<float>(color) + (1.0f - alpha) * static_cast<float>(base));
}

__device__ inline void writePixel(unsigned char* frame,
                                  int pitch,
                                  int x,
                                  int y,
                                  int width,
                                  int height,
                                  unsigned char b,
                                  unsigned char g,
                                  unsigned char r,
                                  float alpha) {
    if (x < 0 || y < 0 || x >= width || y >= height) {
        return;
    }
    unsigned char* row = frame + static_cast<std::size_t>(y) * static_cast<std::size_t>(pitch);
    unsigned char* pixel = row + static_cast<std::size_t>(x) * 3ull;
    pixel[0] = blendComponent(pixel[0], b, alpha);
    pixel[1] = blendComponent(pixel[1], g, alpha);
    pixel[2] = blendComponent(pixel[2], r, alpha);
}

__global__ void draw_boxes_kernel(unsigned char* frame,
                                  int width,
                                  int height,
                                  int pitch,
                                  const DeviceDetection* detections,
                                  int count,
                                  float alpha,
                                  int border) {
    const int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= count) {
        return;
    }

    const auto detection = detections[idx];
    const int x1 = detection.x1;
    const int y1 = detection.y1;
    const int x2 = detection.x2;
    const int y2 = detection.y2;

    // Draw border lines
    for (int offset = 0; offset < border; ++offset) {
        const int top_y = y1 + offset;
        const int bottom_y = y2 - offset;
        for (int x = x1; x <= x2; ++x) {
            writePixel(frame, pitch, x, top_y, width, height, detection.b, detection.g, detection.r, 1.0f);
            writePixel(frame, pitch, x, bottom_y, width, height, detection.b, detection.g, detection.r, 1.0f);
        }

        const int left_x = x1 + offset;
        const int right_x = x2 - offset;
        for (int y = y1; y <= y2; ++y) {
            writePixel(frame, pitch, left_x, y, width, height, detection.b, detection.g, detection.r, 1.0f);
            writePixel(frame, pitch, right_x, y, width, height, detection.b, detection.g, detection.r, 1.0f);
        }
    }

    const int inner_x1 = x1 + border;
    const int inner_x2 = x2 - border;
    const int inner_y1 = y1 + border;
    const int inner_y2 = y2 - border;

    if (inner_x1 >= inner_x2 || inner_y1 >= inner_y2) {
        return;
    }

    for (int y = inner_y1; y <= inner_y2; ++y) {
        for (int x = inner_x1; x <= inner_x2; ++x) {
            writePixel(frame, pitch, x, y, width, height, detection.b, detection.g, detection.r, alpha);
        }
    }
}

} // namespace

bool launchDrawBoxes(unsigned char* frame,
                     int width,
                     int height,
                     int pitch,
                     const DeviceDetection* detections,
                     int count,
                     float alpha,
                     int border) {
    if (!frame || !detections || count <= 0) {
        return true;
    }

    const int threads = 64;
    const int blocks = (count + threads - 1) / threads;
    draw_boxes_kernel<<<blocks, threads>>>(frame, width, height, pitch, detections, count, alpha, border);
    return cudaPeekAtLastError() == cudaSuccess;
}

} // namespace va::analyzer::cuda
