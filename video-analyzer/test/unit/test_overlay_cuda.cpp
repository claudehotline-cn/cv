#include "analyzer/renderer_overlay_cuda.hpp"
#include "analyzer/interfaces.hpp"
#include "core/utils.hpp"

#include <cstdio>
#include <cstdlib>
#include <vector>
#include <iostream>

#ifdef _WIN32
#include <windows.h>
#endif

#ifdef USE_CUDA
#include <cuda_runtime.h>
#endif

using va::analyzer::OverlayRendererCUDA;
using va::core::Frame;
using va::core::ModelOutput;
using va::core::Box;
using va::core::PixelFormat;

int main(){
#ifndef USE_CUDA
    std::cout << "SKIP: USE_CUDA not defined" << std::endl;
    return 0;
#else
    const int W = 64, H = 48;
    uint8_t* d_y = nullptr; size_t pitchY = 0;
    uint8_t* d_uv = nullptr; size_t pitchUV = 0;
    // Allocate NV12 planes
    if (cudaMallocPitch((void**)&d_y, &pitchY, W, H) != cudaSuccess) { std::cerr << "cudaMallocPitch Y failed" << std::endl; return 1; }
    if (cudaMallocPitch((void**)&d_uv, &pitchUV, W, H/2) != cudaSuccess) { std::cerr << "cudaMallocPitch UV failed" << std::endl; return 2; }
    // Initialize Y=0, UV=128
    if (cudaMemset2D(d_y, pitchY, 0, W, H) != cudaSuccess) { std::cerr << "memset Y failed" << std::endl; return 3; }
    if (cudaMemset2D(d_uv, pitchUV, 128, W, H/2) != cudaSuccess) { std::cerr << "memset UV failed" << std::endl; return 4; }

    Frame f; f.width=W; f.height=H; f.has_device_surface=true; f.device.on_gpu=true; f.device.fmt=PixelFormat::NV12; f.device.data0=d_y; f.device.data1=d_uv; f.device.pitch0=(int)pitchY; f.device.pitch1=(int)pitchUV; f.device.width=W; f.device.height=H;

    ModelOutput mo; Box b; b.x1=10; b.y1=8; b.x2=30; b.y2=24; b.score=0.9f; b.cls=0; mo.boxes.push_back(b);

    OverlayRendererCUDA ren; Frame out;
    if (!ren.draw(f, mo, out)) { std::cerr << "draw returned false" << std::endl; return 5; }

    // Copy Y/UV planes to host and verify border pixels changed
    std::vector<uint8_t> yhost((size_t)pitchY * H, 0);
    if (cudaMemcpy2D(yhost.data(), pitchY, d_y, pitchY, W, H, cudaMemcpyDeviceToHost) != cudaSuccess) { std::cerr << "copy Y back failed" << std::endl; return 6; }
    std::vector<uint8_t> uvhost((size_t)pitchUV * (H/2), 0);
    if (cudaMemcpy2D(uvhost.data(), pitchUV, d_uv, pitchUV, W, H/2, cudaMemcpyDeviceToHost) != cudaSuccess) { std::cerr << "copy UV back failed" << std::endl; return 6; }

    auto pix = [&](int x,int y)->uint8_t { return yhost[(size_t)y*pitchY + x]; };
    // Check a top border pixel and an interior non-border pixel
    uint8_t borderY = pix( (int)b.x1 + 1, (int)b.y1 );
    uint8_t innerY  = pix( (int)b.x1 + 5, (int)b.y1 + 5 );
    if (borderY == 0) { std::cerr << "expected border Y!=0" << std::endl; return 7; }
    if (borderY == innerY) { std::cerr << "border Y equals inner Y unexpectedly" << std::endl; return 8; }

    // Check UV border changed from neutral 128
    auto uv_at = [&](int x, int y){ size_t off = (size_t)(y/2) * pitchUV + (size_t)(x/2) * 2; return std::pair<uint8_t,uint8_t>{ uvhost[off+0], uvhost[off+1] }; };
    auto uvBorder = uv_at((int)b.x1 + 1, (int)b.y1);
    if (uvBorder.first == 128 && uvBorder.second == 128) { std::cerr << "expected colored UV at border" << std::endl; return 9; }

    cudaFree(d_y); cudaFree(d_uv);
    std::cout << "OK: CUDA NV12 overlay drew colored rectangle border (Y/UV changed)." << std::endl;
    return 0;
#endif
}
