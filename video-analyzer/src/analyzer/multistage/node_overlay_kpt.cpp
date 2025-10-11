#include "analyzer/multistage/node_overlay_kpt.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include <opencv2/imgproc.hpp>
#include "core/logger.hpp"

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
    if (p.frame.width <= 0 || p.frame.height <= 0 || p.frame.bgr.empty()) {
        VA_LOG_C(::va::core::LogLevel::Debug, "ms.overlay.kpt") << "skip: frame.bgr empty or size invalid";
        return true;
    }
    const int N = static_cast<int>(t.shape[0]);
    const int K = static_cast<int>(t.shape[1]);
    const float* data = static_cast<const float*>(t.data);

    cv::Mat img(p.frame.height, p.frame.width, CV_8UC3, p.frame.bgr.data());
    auto colorFor = [](int idx){ return cv::Scalar((37*idx)%255, (17*idx)%255, (233*idx)%255); };

    // Draw skeleton first (lines)
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
    // Draw points
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

