#include "analyzer/cuda/renderer_overlay_cuda.hpp"

#include <cuda_runtime.h>

namespace {

constexpr int kFontWidth = 5;
constexpr int kFontHeight = 7;
constexpr int kFontSpacing = 1;
constexpr int kLabelPadX = 4;
constexpr int kLabelPadY = 3;

struct Glyph {
    unsigned char rows[kFontHeight];
};

struct GlyphEntry {
    char ch;
    Glyph glyph;
};

__device__ __constant__ GlyphEntry kGlyphTable[] = {
    {' ', {{0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00}}},
    {'0', {{0x0E, 0x11, 0x13, 0x15, 0x19, 0x11, 0x0E}}},
    {'1', {{0x04, 0x0C, 0x04, 0x04, 0x04, 0x04, 0x0E}}},
    {'2', {{0x0E, 0x11, 0x01, 0x02, 0x04, 0x08, 0x1F}}},
    {'3', {{0x0E, 0x11, 0x01, 0x06, 0x01, 0x11, 0x0E}}},
    {'4', {{0x02, 0x06, 0x0A, 0x12, 0x1F, 0x02, 0x02}}},
    {'5', {{0x1F, 0x10, 0x1E, 0x01, 0x01, 0x11, 0x0E}}},
    {'6', {{0x06, 0x08, 0x10, 0x1E, 0x11, 0x11, 0x0E}}},
    {'7', {{0x1F, 0x01, 0x02, 0x04, 0x08, 0x08, 0x08}}},
    {'8', {{0x0E, 0x11, 0x11, 0x0E, 0x11, 0x11, 0x0E}}},
    {'9', {{0x0E, 0x11, 0x11, 0x0F, 0x01, 0x02, 0x0C}}},
    {'C', {{0x0E, 0x11, 0x10, 0x10, 0x10, 0x11, 0x0E}}},
    {'L', {{0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x1F}}},
    {'S', {{0x0E, 0x11, 0x10, 0x0E, 0x01, 0x11, 0x0E}}},
    {'|', {{0x04, 0x04, 0x04, 0x04, 0x04, 0x04, 0x04}}},
    {'%', {{0x18, 0x19, 0x02, 0x04, 0x08, 0x13, 0x03}}},
    {'-', {{0x00, 0x00, 0x00, 0x1F, 0x00, 0x00, 0x00}}}
};

__device__ inline const Glyph* lookupGlyph(char ch) {
    const int table_size = sizeof(kGlyphTable) / sizeof(kGlyphTable[0]);
    for (int i = 0; i < table_size; ++i) {
        if (kGlyphTable[i].ch == ch) {
            return &kGlyphTable[i].glyph;
        }
    }
    return nullptr;
}

__device__ inline unsigned char blendComponent(unsigned char base, unsigned char color, float alpha) {
    return static_cast<unsigned char>(alpha * static_cast<float>(color) + (1.0f - alpha) * static_cast<float>(base));
}

__device__ inline void blendPixel(unsigned char* frame,
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

__device__ inline void writePixelSolid(unsigned char* frame,
                                       int pitch,
                                       int x,
                                       int y,
                                       int width,
                                       int height,
                                       unsigned char b,
                                       unsigned char g,
                                       unsigned char r) {
    if (x < 0 || y < 0 || x >= width || y >= height) {
        return;
    }
    unsigned char* row = frame + static_cast<std::size_t>(y) * static_cast<std::size_t>(pitch);
    unsigned char* pixel = row + static_cast<std::size_t>(x) * 3ull;
    pixel[0] = b;
    pixel[1] = g;
    pixel[2] = r;
}

__global__ void draw_labels_kernel(unsigned char* frame,
                                   int width,
                                   int height,
                                   int pitch,
                                   const va::analyzer::cuda::DeviceLabel* labels,
                                   int count,
                                   const char* text_buffer,
                                   int text_bytes,
                                   float alpha) {
    const int idx = blockIdx.x * blockDim.x + threadIdx.x;
    if (idx >= count) {
        return;
    }

    const va::analyzer::cuda::DeviceLabel label = labels[idx];
    if (label.text_offset < 0 || label.text_length <= 0) {
        return;
    }
    if (label.text_offset + label.text_length > text_bytes) {
        return;
    }

    const char* text = text_buffer + label.text_offset;

    for (int y = 0; y < label.height; ++y) {
        for (int x = 0; x < label.width; ++x) {
            blendPixel(frame,
                       pitch,
                       label.x + x,
                       label.y + y,
                       width,
                       height,
                       label.b,
                       label.g,
                       label.r,
                       alpha);
        }
    }

    const int text_origin_x = label.x + kLabelPadX;
    const int text_origin_y = label.y + kLabelPadY;

    for (int i = 0; i < label.text_length; ++i) {
        const char ch = text[i];
        const Glyph* glyph = lookupGlyph(ch);
        if (!glyph) {
            continue;
        }
        const int glyph_x = text_origin_x + i * (kFontWidth + kFontSpacing);
        for (int row = 0; row < kFontHeight; ++row) {
            const unsigned char pattern = (*glyph).rows[row];
            for (int col = 0; col < kFontWidth; ++col) {
                if ((pattern >> (kFontWidth - 1 - col)) & 0x01) {
                    writePixelSolid(frame,
                                    pitch,
                                    glyph_x + col,
                                    text_origin_y + row,
                                    width,
                                    height,
                                    255,
                                    255,
                                    255);
                }
            }
        }
    }
}

} // namespace

namespace va::analyzer::cuda {

bool launchDrawLabels(unsigned char* frame,
                      int width,
                      int height,
                      int pitch,
                      const DeviceLabel* labels,
                      int count,
                      const char* text_buffer,
                      int text_bytes,
                      float alpha) {
    if (!frame || !labels || !text_buffer || count <= 0 || text_bytes <= 0) {
        return true;
    }
    const int threads = 64;
    const int blocks = (count + threads - 1) / threads;
    draw_labels_kernel<<<blocks, threads>>>(frame,
                                            width,
                                            height,
                                            pitch,
                                            labels,
                                            count,
                                            text_buffer,
                                            text_bytes,
                                            alpha);
    return cudaPeekAtLastError() == cudaSuccess;
}

} // namespace va::analyzer::cuda

