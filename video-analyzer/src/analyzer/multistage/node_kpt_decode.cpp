#include "analyzer/multistage/node_kpt_decode.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"

using va::analyzer::multistage::util::get_or;
using va::analyzer::multistage::util::get_or_int;
using va::analyzer::multistage::util::get_or_float;

namespace va { namespace analyzer { namespace multistage {

NodeKptDecode::NodeKptDecode(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in"); it != cfg.end()) in_key_ = it->second;
    if (auto it = cfg.find("out"); it != cfg.end()) out_key_ = it->second;
    kpt_offset_ = get_or_int(cfg, "kpt_offset", 5);
    min_score_ = get_or_float(cfg, "min_score", 0.0f);
}

bool NodeKptDecode::process(Packet& p, NodeContext& ctx) {
    auto it = p.tensors.find(in_key_);
    if (it == p.tensors.end()) return false;
    const auto& t = it->second;
    if (t.shape.size() < 3 || t.dtype != va::core::DType::F32 || !t.data) return false;

    const float* data = static_cast<const float*>(t.data);
    int64_t dim0 = t.shape[0];
    int64_t dim1 = t.shape[1];
    int64_t dim2 = t.shape[2];
    if (dim0 != 1) return false;

    // Determine channels_first and attributes count
    auto looks_like_attrs = [](int64_t v){ return v >= 3 && v <= 512; };
    int64_t candA_det = dim1, candA_attr = dim2; // [N, C]
    int64_t candB_det = dim2, candB_attr = dim1; // [C, N]
    bool channels_first = false;
    if (looks_like_attrs(candB_attr) && !looks_like_attrs(candA_attr)) channels_first = true;
    else if (looks_like_attrs(candB_attr) && looks_like_attrs(candA_attr)) channels_first = (candB_det >= candA_det);
    else if (!looks_like_attrs(candA_attr)) channels_first = true;
    const int num_det = static_cast<int>(channels_first ? candB_det : candA_det);
    const int num_attrs = static_cast<int>(channels_first ? candB_attr : candA_attr);
    if (num_det <= 0 || num_attrs < 3) return false;

    // Infer keypoints count
    int kpt_ch = num_attrs - kpt_offset_;
    if (kpt_ch < 3) return false;
    if (kpt_ch % 3 != 0) {
        // Some models don't include box; try treat whole attrs as keypoints
        if (num_attrs % 3 != 0) return false;
        kpt_offset_ = 0;
        kpt_ch = num_attrs;
    }
    const int K = kpt_ch / 3;

    // Prepare output buffer [N, K, 3] (x,y,score) in original image coords
    buffer_.assign(static_cast<size_t>(num_det) * static_cast<size_t>(K) * 3ull, 0.0f);
    auto at = [&](int det, int ch){ return channels_first ? data[ch * num_det + det] : data[det * num_attrs + ch]; };

    const auto& meta = p.letterbox;
    const float scale = (meta.scale == 0.0f ? 1.0f : meta.scale);
    const int orig_w = meta.original_width > 0 ? meta.original_width : meta.input_width;
    const int orig_h = meta.original_height > 0 ? meta.original_height : meta.input_height;

    for (int i = 0; i < num_det; ++i) {
        for (int k = 0; k < K; ++k) {
            const int base = kpt_offset_ + k * 3;
            float x = at(i, base + 0);
            float y = at(i, base + 1);
            float s = at(i, base + 2);
            // Un-letterbox to original image coords
            float ox = (x - static_cast<float>(meta.pad_x)) / (scale == 0.0f ? 1.0f : scale);
            float oy = (y - static_cast<float>(meta.pad_y)) / (scale == 0.0f ? 1.0f : scale);
            // Clamp
            if (ox < 0.0f) ox = 0.0f; if (oy < 0.0f) oy = 0.0f;
            if (ox > static_cast<float>(orig_w - 1)) ox = static_cast<float>(orig_w - 1);
            if (oy > static_cast<float>(orig_h - 1)) oy = static_cast<float>(orig_h - 1);
            if (s < min_score_) { s = 0.0f; }
            size_t idx = (static_cast<size_t>(i) * K + static_cast<size_t>(k)) * 3ull;
            buffer_[idx + 0] = ox;
            buffer_[idx + 1] = oy;
            buffer_[idx + 2] = s;
        }
    }

    va::core::TensorView tv;
    tv.data = buffer_.data();
    tv.shape = { num_det, K, 3 };
    tv.dtype = va::core::DType::F32;
    tv.on_gpu = false;
    p.tensors[out_key_] = tv;
    return true;
}

} } } // namespace

