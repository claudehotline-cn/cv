#include "analyzer/multistage/node_overlay_kpt.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include <opencv2/imgproc.hpp>
#include "core/logger.hpp"
#ifdef USE_CUDA
#  if defined(__has_include)
#    if __has_include(<cuda_runtime.h>)
#      include <cuda_runtime.h>
#      define VA_MS_KPT_HAS_CUDA 1
#    else
#      define VA_MS_KPT_HAS_CUDA 0
#    endif
#  else
#    include <cuda_runtime.h>
#    define VA_MS_KPT_HAS_CUDA 1
#  endif
#else
#  define VA_MS_KPT_HAS_CUDA 0
#endif

using va::analyzer::multistage::util::get_or_int;
using va::analyzer::multistage::util::get_or_float;

namespace va { namespace analyzer { namespace multistage {

static std::vector<std::pair<int,int>> parse_skeleton(const std::string& s) {
    std::vector<std::pair<int,int>> out;
    std::string cur; int state=0, a=0, b=0;
    for (size_t i=0;i<=s.size();++i) {
        char c = (i<s.size()? s[i] : ',');
        if (state==0) {
            if (c=='-' ) { try { a = std::stoi(cur); } catch (...) { a = -1; } cur.clear(); state=1; }
            else if (c==',' ) { cur.clear(); }
            else { cur.push_back(c); }
        } else {
            if (c==',' ) { try { b = std::stoi(cur); } catch (...) { b = -1; } cur.clear(); state=0; if (a>=0 && b>=0) out.emplace_back(a,b); }
            else { cur.push_back(c); }
        }
    }
    return out;
}

NodeOverlayKpt::NodeOverlayKpt(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in"); it != cfg.end()) in_key_ = it->second;
    radius_ = get_or_int(cfg, "radius", 3);
    thickness_ = get_or_int(cfg, "thickness", 2);
    min_score_ = get_or_float(cfg, "min_score", 0.0f);
    draw_skeleton_ = get_or_int(cfg, "draw_skeleton", 0) != 0;
    if (auto it = cfg.find("skeleton"); it != cfg.end()) {
        edges_ = parse_skeleton(it->second);
    }
}

bool NodeOverlayKpt::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return true; // no kpt -> no-op
    const auto& t = it->second;
    if (t.shape.size() != 3 || t.dtype != va::core::DType::F32 || !t.data) return true;
    if (p.frame.width <= 0 || p.frame.height <= 0) {
        VA_LOG_C(::va::core::LogLevel::Debug, "ms.overlay.kpt") << "skip: frame.bgr empty or size invalid";
        return true;
    }
    const int N = static_cast<int>(t.shape[0]);
    const int K = static_cast<int>(t.shape[1]);
    const float* data = static_cast<const float*>(t.data);

#if VA_MS_KPT_HAS_CUDA
    if (p.frame.has_device_surface && p.frame.device.on_gpu && p.frame.device.fmt == va::core::PixelFormat::NV12) {
        // Device NV12 path: draw small squares around keypoints by Y memset + UV memcpy patterns.
        uint8_t* yBase = static_cast<uint8_t*>(p.frame.device.data0);
        uint8_t* uvBase = static_cast<uint8_t*>(p.frame.device.data1);
        const size_t yPitch = static_cast<size_t>(p.frame.device.pitch0);
        const size_t uvPitch = static_cast<size_t>(p.frame.device.pitch1);
        auto srgb_to_lin = [](float c){ return c <= 0.04045f ? c/12.92f : std::pow((c+0.055f)/1.055f, 2.4); };
        auto rgb_to_yuv709_limited = [&](unsigned char R8,unsigned char G8,unsigned char B8,
                                         unsigned char& Yc,unsigned char& Uc,unsigned char& Vc){
            float R = (float)srgb_to_lin(R8/255.0f);
            float G = (float)srgb_to_lin(G8/255.0f);
            float B = (float)srgb_to_lin(B8/255.0f);
            float Yf = 0.2126f*R + 0.7152f*G + 0.0722f*B;
            float Cb = (B - Yf) / 1.8556f;
            float Cr = (R - Yf) / 1.5748f;
            int yv = (int)std::round(16.0 + 219.0 * Yf);
            int uv = (int)std::round(128.0 + 224.0 * Cb);
            int vv = (int)std::round(128.0 + 224.0 * Cr);
            if (yv<16) yv=16; if (yv>235) yv=235; if (uv<16) uv=16; if (uv>240) uv=240; if (vv<16) vv=16; if (vv>240) vv=240;
            Yc=(unsigned char)yv; Uc=(unsigned char)uv; Vc=(unsigned char)vv;
        };
        auto colorForBGR = [](int idx){ return std::array<unsigned char,3>{ (unsigned char)((233*idx)%255), (unsigned char)((17*idx)%255), (unsigned char)((37*idx)%255) }; };
        const int tb = std::max(1, radius_);

        auto draw_square_nv12 = [&](int x1, int y1, int x2, int y2, unsigned char Yc, unsigned char Uc, unsigned char Vc){
            if (x2 < x1 || y2 < y1) return;
            // Fill Y square
            size_t rowBytes = (size_t)(x2 - x1 + 1);
            cudaMemset2D(yBase + y1 * yPitch + x1, yPitch, Yc, rowBytes, (size_t)(y2 - y1 + 1));
            // Fill UV square (2x2)
            int uv_x1 = x1/2, uv_x2 = x2/2, uv_y1 = y1/2, uv_y2 = y2/2;
            size_t uvRowBytes = (size_t)((uv_x2 - uv_x1 + 1) * 2);
            std::vector<uint8_t> uvRow(uvRowBytes);
            for (size_t kk=0; kk<uvRowBytes; kk+=2){ uvRow[kk]=Uc; uvRow[kk+1]=Vc; }
            for (int uyy = uv_y1; uyy <= uv_y2; ++uyy) {
                cudaMemcpy(uvBase + uyy * uvPitch + uv_x1*2, uvRow.data(), uvRowBytes, cudaMemcpyHostToDevice);
            }
        };

        // Optional: draw skeleton lines as contiguous segments by horizontal row fills
        auto draw_line_nv12 = [&](int x0,int y0,int x1,int y1, unsigned char Yc, unsigned char Uc, unsigned char Vc){
            // Ensure within bounds
            x0 = std::max(0, std::min(p.frame.device.width - 1, x0));
            x1 = std::max(0, std::min(p.frame.device.width - 1, x1));
            y0 = std::max(0, std::min(p.frame.device.height - 1, y0));
            y1 = std::max(0, std::min(p.frame.device.height - 1, y1));
            int dy = y1 - y0; int dx = x1 - x0;
            if (std::abs(dy) >= std::abs(dx)) {
                // Step over y
                if (y0 > y1) { std::swap(y0,y1); std::swap(x0,x1); dy = y1-y0; dx = x1-x0; }
                for (int y = y0; y <= y1; ++y) {
                    float t = (dy==0)? 0.0f : (float)(y - y0) / (float)dy;
                    int x = (int)std::round(x0 + t * dx);
                    int xs = std::max(0, x - tb), xe = std::min(p.frame.device.width - 1, x + tb);
                    draw_square_nv12(xs, y, xe, y, Yc, Uc, Vc);
                }
            } else {
                // Step over x
                if (x0 > x1) { std::swap(y0,y1); std::swap(x0,x1); dy = y1-y0; dx = x1-x0; }
                for (int x = x0; x <= x1; ++x) {
                    float t = (dx==0)? 0.0f : (float)(x - x0) / (float)dx;
                    int y = (int)std::round(y0 + t * dy);
                    int ys = std::max(0, y - tb), ye = std::min(p.frame.device.height - 1, y + tb);
                    // vertical band approximated by multiple horizontal 1-px rows
                    for (int yy = ys; yy <= ye; ++yy) {
                        draw_square_nv12(x, yy, x, yy, Yc, Uc, Vc);
                    }
                }
            }
        };
        if (draw_skeleton_ && !edges_.empty()) {
            for (int i=0;i<N;++i) {
                for (auto e : edges_) {
                    int a = e.first, b = e.second;
                    if (a<0||a>=K||b<0||b>=K) continue;
                    size_t ia = (static_cast<size_t>(i)*K + static_cast<size_t>(a))*3ull;
                    size_t ib = (static_cast<size_t>(i)*K + static_cast<size_t>(b))*3ull;
                    float xa = data[ia+0], ya = data[ia+1], sa = data[ia+2];
                    float xb = data[ib+0], yb = data[ib+1], sb = data[ib+2];
                    if (sa < min_score_ || sb < min_score_) continue;
                    int x0 = (int)std::round(xa), y0 = (int)std::round(ya);
                    int x1 = (int)std::round(xb), y1 = (int)std::round(yb);
                    auto rgb = colorForBGR(a);
                    unsigned char Yc=235, Uc=128, Vc=128; rgb_to_yuv709_limited(rgb[2], rgb[1], rgb[0], Yc, Uc, Vc);
                    draw_line_nv12(x0,y0,x1,y1,Yc,Uc,Vc);
                }
            }
        }

        // Draw points as squares
        for (int i=0;i<N;++i) {
            for (int k=0;k<K;++k) {
                size_t idx = (static_cast<size_t>(i)*K + static_cast<size_t>(k))*3ull;
                float xf = data[idx+0], yf = data[idx+1], s = data[idx+2];
                if (s < min_score_) continue;
                int x = std::max(0, std::min(p.frame.device.width - 1, (int)std::round(xf)));
                int y = std::max(0, std::min(p.frame.device.height - 1, (int)std::round(yf)));
                int xs1 = std::max(0, x - tb), xs2 = std::min(p.frame.device.width - 1, x + tb);
                int ys1 = std::max(0, y - tb), ys2 = std::min(p.frame.device.height - 1, y + tb);
                auto rgb = colorForBGR(k);
                unsigned char Yc=235, Uc=128, Vc=128; rgb_to_yuv709_limited(rgb[2], rgb[1], rgb[0], Yc, Uc, Vc);
                draw_square_nv12(xs1, ys1, xs2, ys2, Yc, Uc, Vc);
            }
        }
        return true;
    }
#endif
    // CPU BGR path
    if (p.frame.bgr.empty()) return true;
    cv::Mat img(p.frame.height, p.frame.width, CV_8UC3, p.frame.bgr.data());
    auto colorFor = [](int idx){ return cv::Scalar((37*idx)%255, (17*idx)%255, (233*idx)%255); };
    if (draw_skeleton_ && !edges_.empty()) {
        for (int i=0;i<N;++i) {
            for (auto e : edges_) {
                int a = e.first, b = e.second;
                if (a<0||a>=K||b<0||b>=K) continue;
                size_t ia = (static_cast<size_t>(i)*K + static_cast<size_t>(a))*3ull;
                size_t ib = (static_cast<size_t>(i)*K + static_cast<size_t>(b))*3ull;
                float xa = data[ia+0], ya = data[ia+1], sa = data[ia+2];
                float xb = data[ib+0], yb = data[ib+1], sb = data[ib+2];
                if (sa < min_score_ || sb < min_score_) continue;
                cv::line(img, cv::Point((int)std::round(xa),(int)std::round(ya)),
                              cv::Point((int)std::round(xb),(int)std::round(yb)), colorFor(a), thickness_, cv::LINE_AA);
            }
        }
    }
    for (int i=0;i<N;++i) {
        for (int k=0;k<K;++k) {
            size_t idx = (static_cast<size_t>(i)*K + static_cast<size_t>(k))*3ull;
            float x = data[idx+0], y = data[idx+1], s = data[idx+2];
            if (s < min_score_) continue;
            cv::circle(img, cv::Point((int)std::round(x),(int)std::round(y)), radius_, colorFor(k), cv::FILLED, cv::LINE_AA);
        }
    }
    return true;
}

} } } // namespace
