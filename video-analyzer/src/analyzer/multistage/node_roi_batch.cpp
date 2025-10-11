#include "analyzer/multistage/node_roi_batch.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"
#include <opencv2/imgproc.hpp>

using va::analyzer::multistage::util::get_or_int;
using va::analyzer::multistage::util::get_or;

namespace va { namespace analyzer { namespace multistage {

NodeRoiBatch::NodeRoiBatch(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in_rois"); it != cfg.end()) in_rois_key_ = it->second;
    if (auto it = cfg.find("out"); it != cfg.end()) out_key_ = it->second;
    out_w_ = get_or_int(cfg, "out_w", 128);
    out_h_ = get_or_int(cfg, "out_h", 128);
    normalize_ = get_or_int(cfg, "normalize", 1) != 0;
    max_rois_ = get_or_int(cfg, "max_rois", 0);
}

bool NodeRoiBatch::process(Packet& p, NodeContext& /*ctx*/) {
    auto it = p.rois.find(in_rois_key_);
    if (it == p.rois.end()) {
        // No ROIs -> clear tensor
        p.tensors.erase(out_key_);
        return true;
    }
    const auto& rois = it->second;
    if (p.frame.bgr.empty()) {
        VA_LOG_C(::va::core::LogLevel::Warn, "ms.roi_batch") << "frame.bgr is empty; ROI batch requires host BGR";
        return false;
    }
    const int src_w = p.frame.width;
    const int src_h = p.frame.height;
    if (src_w <= 0 || src_h <= 0) return false;

    int use_n = static_cast<int>(rois.size());
    if (max_rois_ > 0) use_n = std::min(use_n, max_rois_);
    if (use_n <= 0) {
        // Produce empty batch tensor [0,3,H,W] by convention -> skip setting tensor
        p.tensors.erase(out_key_);
        return true;
    }

    const size_t plane = static_cast<size_t>(out_w_) * static_cast<size_t>(out_h_);
    buffer_.assign(static_cast<size_t>(use_n) * 3ull * plane, 0.0f);

    cv::Mat src(src_h, src_w, CV_8UC3, const_cast<uint8_t*>(p.frame.bgr.data()));
    for (int i = 0; i < use_n; ++i) {
        auto b = rois[i];
        int x1 = std::max(0, static_cast<int>(std::floor(b.x1)));
        int y1 = std::max(0, static_cast<int>(std::floor(b.y1)));
        int x2 = std::min(src_w - 1, static_cast<int>(std::ceil(b.x2)));
        int y2 = std::min(src_h - 1, static_cast<int>(std::ceil(b.y2)));
        if (x2 <= x1 || y2 <= y1) continue;
        cv::Rect r(x1, y1, x2 - x1 + 1, y2 - y1 + 1);
        r &= cv::Rect(0, 0, src_w, src_h);
        if (r.width <= 0 || r.height <= 0) continue;
        cv::Mat crop = src(r);
        // Letterbox crop to out_w_ x out_h_
        float scale = std::min(static_cast<float>(out_w_) / r.width, static_cast<float>(out_h_) / r.height);
        const int rw = std::max(1, static_cast<int>(std::round(r.width * scale)));
        const int rh = std::max(1, static_cast<int>(std::round(r.height * scale)));
        const int pad_x = (out_w_ - rw) / 2;
        const int pad_y = (out_h_ - rh) / 2;
        cv::Mat resized; cv::resize(crop, resized, cv::Size(rw, rh));
        cv::Mat letter(out_h_, out_w_, CV_8UC3, cv::Scalar(114,114,114));
        resized.copyTo(letter(cv::Rect(pad_x, pad_y, rw, rh)));
        cv::Mat letterf;
        if (normalize_) {
            letter.convertTo(letterf, CV_32F, 1.0/255.0);
        } else {
            letter.convertTo(letterf, CV_32F);
        }
        std::vector<cv::Mat> ch(3); cv::split(letterf, ch);
        float* base = buffer_.data() + static_cast<size_t>(i) * 3ull * plane;
        std::memcpy(base + plane * 0, ch[0].ptr<float>(), plane * sizeof(float));
        std::memcpy(base + plane * 1, ch[1].ptr<float>(), plane * sizeof(float));
        std::memcpy(base + plane * 2, ch[2].ptr<float>(), plane * sizeof(float));
    }

    va::core::TensorView tv;
    tv.data = buffer_.data();
    tv.shape = { use_n, 3, out_h_, out_w_ };
    tv.dtype = va::core::DType::F32;
    tv.on_gpu = false;
    p.tensors[out_key_] = tv;
    return true;
}

} } } // namespace

