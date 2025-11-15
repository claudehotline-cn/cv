#include "analyzer/multistage/node_track_ocsort.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"
#include "analyzer/logging_util.hpp"
#if defined(USE_CUDA)
#include <cuda_runtime.h>
#endif
#include <algorithm>
#include <cmath>

using va::analyzer::multistage::util::get_or_float;
using va::analyzer::multistage::util::get_or_int;

namespace va { namespace analyzer { namespace multistage {

NodeTrackOcsort::NodeTrackOcsort(const std::unordered_map<std::string,std::string>& cfg) {
    if (auto it = cfg.find("in_rois"); it != cfg.end()) in_rois_key_ = it->second;
    if (auto it = cfg.find("out_rois"); it != cfg.end()) out_rois_key_ = it->second;
    if (auto it = cfg.find("feat_key"); it != cfg.end()) feat_key_ = it->second;
    iou_thresh_ = get_or_float(cfg, "iou_thresh", 0.3f);
    max_missed_ = get_or_int(cfg, "max_missed", 30);
    if (max_missed_ < 1) max_missed_ = 1;
    feat_alpha_ = get_or_float(cfg, "feat_alpha", 0.9f);
    if (feat_alpha_ < 0.0f) feat_alpha_ = 0.0f;
    if (feat_alpha_ > 1.0f) feat_alpha_ = 1.0f;
    w_iou_ = get_or_float(cfg, "w_iou", 0.5f);
    w_reid_ = get_or_float(cfg, "w_reid", 0.5f);
    max_tracks_ = get_or_int(cfg, "max_tracks", 256);
    if (max_tracks_ < 16) max_tracks_ = 16;
    if (max_tracks_ > 512) max_tracks_ = 512;
}

bool NodeTrackOcsort::open(NodeContext& ctx) {
#if defined(USE_CUDA)
    // 仅在具备 GPU 上下文时尝试启用 GPU 追踪路径
    if (ctx.gpu_pool && ctx.stream) {
        use_gpu_ = true;
    } else {
        use_gpu_ = false;
    }
    gpu_state_ready_ = false;
    (void)ctx;
#else
    (void)ctx;
#endif
    return true;
}

void NodeTrackOcsort::close(NodeContext& ctx) {
    (void)ctx;
#if defined(USE_CUDA)
    if (gpu_state_ready_) {
        va::analyzer::cudaops::ocsort_free_state(gpu_state_);
        gpu_state_ready_ = false;
    }
    use_gpu_ = false;
#endif
    tracks_.clear();
    next_id_ = 1;
}

float NodeTrackOcsort::iou(const Roi& a, const Roi& b) {
    const float x1 = std::max(a.x1, b.x1);
    const float y1 = std::max(a.y1, b.y1);
    const float x2 = std::min(a.x2, b.x2);
    const float y2 = std::min(a.y2, b.y2);
    const float w = std::max(0.0f, x2 - x1);
    const float h = std::max(0.0f, y2 - y1);
    const float inter = w * h;
    if (inter <= 0.0f) return 0.0f;
    const float areaA = std::max(0.0f, a.x2 - a.x1) * std::max(0.0f, a.y2 - a.y1);
    const float areaB = std::max(0.0f, b.x2 - b.x1) * std::max(0.0f, b.y2 - b.y1);
    const float uni = areaA + areaB - inter;
    if (uni <= 0.0f) return 0.0f;
    return inter / uni;
}

void NodeTrackOcsort::l2_normalize(std::vector<float>& v) {
    double ss = 0.0;
    for (float x : v) ss += static_cast<double>(x) * static_cast<double>(x);
    if (ss <= 1e-12) return;
    const double inv = 1.0 / std::sqrt(ss);
    for (auto& x : v) x = static_cast<float>(static_cast<double>(x) * inv);
}

float NodeTrackOcsort::cosine(const std::vector<float>& a, const float* b, int D) {
    if (!b || a.size() != static_cast<size_t>(D) || D <= 0) return 0.0f;
    double dot = 0.0, nb = 0.0;
    for (int i = 0; i < D; ++i) {
        const double va = static_cast<double>(a[i]);
        const double vb = static_cast<double>(b[i]);
        dot += va * vb;
        nb += vb * vb;
    }
    if (nb <= 1e-12) return 0.0f;
    nb = std::sqrt(nb);
    const double na = 1.0; // a 已假定为单位向量（经过 l2_normalize）
    const double denom = na * nb;
    if (denom <= 1e-12) return 0.0f;
    return static_cast<float>(dot / denom);
}

bool NodeTrackOcsort::process(Packet& p, NodeContext& ctx) {
#if defined(USE_CUDA)
    if (use_gpu_) {
        if (process_gpu(p, ctx)) {
            auto lvl = va::analyzer::logutil::log_level_for_tag("ms.track");
            auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.track");
            VA_LOG_THROTTLED(lvl, "ms.track", thr) << "path=gpu";
            return true;
        }
        // GPU 路径失败时回退到 CPU 实现
        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.track");
        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.track");
        VA_LOG_THROTTLED(lvl, "ms.track", thr) << "gpu_path_failed -> fallback cpu";
    }
#endif
    return process_cpu(p);
}

bool NodeTrackOcsort::process_cpu(Packet& p) {
    auto it = p.rois.find(in_rois_key_);
    if (it == p.rois.end()) {
        // 没有检测框时清空输出并衰减已有轨迹
        for (auto& tr : tracks_) {
            tr.updated = false;
            tr.missed++;
        }
        tracks_.erase(std::remove_if(tracks_.begin(), tracks_.end(),
                                     [&](const Track& t){ return t.missed > max_missed_; }),
                      tracks_.end());
        p.rois.erase(out_rois_key_);
        return true;
    }
    const auto& dets = it->second;

    // 读取 ReID 特征 [N,D]（可选）
    const float* feat_data = nullptr;
    int feat_dim = 0;
    bool have_feat = false;
    auto itf = p.tensors.find(feat_key_);
    if (itf != p.tensors.end()) {
        const auto& tv = itf->second;
        if (!tv.on_gpu && tv.dtype == va::core::DType::F32 && tv.shape.size() == 2) {
            const int64_t N = tv.shape[0];
            const int64_t D = tv.shape[1];
            if (N == static_cast<int64_t>(dets.size()) && D > 0) {
                feat_data = static_cast<const float*>(tv.data);
                feat_dim = static_cast<int>(D);
                have_feat = true;
            }
        }
    }

    const size_t T = tracks_.size();
    const size_t D = dets.size();

    // 标记所有轨迹为未更新
    for (auto& tr : tracks_) {
        tr.updated = false;
    }

    // 记录每个检测对应的轨迹索引（-1 表示新建）
    std::vector<int> det_to_track(D, -1);

    if (!tracks_.empty() && !dets.empty()) {
        // 计算匹配得分（IoU + 可选 ReID 余弦相似度），并做简单贪心匹配
        struct Match { int t; int d; float score; };
        std::vector<Match> matches;
        matches.reserve(T * D);
        for (size_t ti = 0; ti < T; ++ti) {
            for (size_t di = 0; di < D; ++di) {
                float v_iou = iou(tracks_[ti].box, dets[di]);
                if (v_iou < iou_thresh_) continue;
                float v_reid = 0.0f;
                if (have_feat && tracks_[ti].has_feat && feat_dim > 0) {
                    const float* f_det = feat_data + static_cast<int>(di) * feat_dim;
                    v_reid = cosine(tracks_[ti].feat, f_det, feat_dim);
                }
                float score = w_iou_ * v_iou + w_reid_ * v_reid;
                matches.push_back(Match{static_cast<int>(ti), static_cast<int>(di), score});
            }
        }
        std::sort(matches.begin(), matches.end(),
                  [](const Match& a, const Match& b){ return a.score > b.score; });

        std::vector<bool> track_used(T, false);
        std::vector<bool> det_used(D, false);
        for (const auto& m : matches) {
            if (m.t < 0 || m.t >= (int)T || m.d < 0 || m.d >= (int)D) continue;
            if (track_used[m.t] || det_used[m.d]) continue;
            track_used[m.t] = true;
            det_used[m.d] = true;
            tracks_[m.t].box = dets[m.d];
            tracks_[m.t].missed = 0;
            tracks_[m.t].updated = true;
            det_to_track[m.d] = m.t;

            // 更新轨迹的 ReID 特征（EMA + L2 归一）
            if (have_feat && feat_dim > 0) {
                const float* f_det = feat_data + static_cast<int>(m.d) * feat_dim;
                auto& feat = tracks_[m.t].feat;
                if (feat.size() != static_cast<size_t>(feat_dim)) {
                    feat.assign(f_det, f_det + feat_dim);
                } else {
                    const float a = feat_alpha_;
                    const float b = 1.0f - a;
                    for (int k = 0; k < feat_dim; ++k) {
                        feat[k] = a * feat[k] + b * f_det[k];
                    }
                }
                l2_normalize(tracks_[m.t].feat);
                tracks_[m.t].has_feat = true;
            }
        }
    }

    // 未匹配的检测生成新轨迹，并初始化特征
    for (size_t di = 0; di < D; ++di) {
        if (det_to_track[di] != -1) continue;
        Track tr;
        tr.id = next_id_++;
        tr.box = dets[di];
        tr.missed = 0;
        tr.updated = true;
        if (have_feat && feat_dim > 0) {
            const float* f_det = feat_data + static_cast<int>(di) * feat_dim;
            tr.feat.assign(f_det, f_det + feat_dim);
            l2_normalize(tr.feat);
            tr.has_feat = true;
        }
        tracks_.push_back(tr);
        det_to_track[di] = static_cast<int>(tracks_.size() - 1);
    }

    // 更新未匹配到检测的轨迹的 missed 计数并删除过期轨迹
    for (auto& tr : tracks_) {
        if (!tr.updated) {
            tr.missed++;
        }
    }
    tracks_.erase(std::remove_if(tracks_.begin(), tracks_.end(),
                                 [&](const Track& t){ return t.missed > max_missed_; }),
                  tracks_.end());

    // 构造输出 ROI：沿用检测框几何与 score，将 cls 字段复用为 track_id
    std::vector<Roi> out;
    out.reserve(D);
    for (size_t di = 0; di < D; ++di) {
        int ti = det_to_track[di];
        if (ti < 0 || ti >= (int)tracks_.size()) continue;
        Roi b = dets[di];
        b.cls = tracks_[ti].id;
        out.push_back(b);
    }

    auto lvl = va::analyzer::logutil::log_level_for_tag("ms.track");
    auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.track");
    VA_LOG_THROTTLED(lvl, "ms.track", thr) << "in=" << dets.size() << " out=" << out.size()
                                           << " tracks=" << tracks_.size();

    p.rois[out_rois_key_] = std::move(out);
    return true;
}

#if defined(USE_CUDA)

bool NodeTrackOcsort::process_gpu(Packet& p, NodeContext& ctx) {
    if (!ctx.gpu_pool || !ctx.stream) {
        return false;
    }
    auto itg = p.gpu_rois.find(in_rois_key_);
    if (itg == p.gpu_rois.end()) {
        // 没有 GPU ROI 时暂不强行拷贝，交给 CPU 路径处理
        return false;
    }
    const auto& gdet = itg->second;
    if (!gdet.d_boxes || gdet.count <= 0) {
        // 只有轨迹衰减，无新的检测框
        if (!gpu_state_ready_) {
            return true; // 无状态且无检测时无需任何操作
        }
        auto err = va::analyzer::cudaops::ocsort_match_and_update(
            gdet,
            nullptr,
            gpu_state_,
            iou_thresh_,
            feat_alpha_,
            w_iou_,
            w_reid_,
            max_missed_,
            1,
            static_cast<cudaStream_t>(ctx.stream));
        if (err != cudaSuccess) return false;
    } else {
        const float* d_feats = nullptr;
        int feat_dim = 0;
        auto itf = p.tensors.find(feat_key_);
        if (itf != p.tensors.end()) {
            const auto& tv = itf->second;
            if (tv.on_gpu && tv.dtype == va::core::DType::F32 && tv.shape.size() == 2) {
                const int64_t N = tv.shape[0];
                const int64_t D = tv.shape[1];
                if (N == static_cast<int64_t>(gdet.count) && D > 0) {
                    d_feats = static_cast<const float*>(tv.data);
                    feat_dim = static_cast<int>(D);
                }
            }
        }
        if (!gpu_state_ready_) {
            int use_feat_dim = feat_dim;
            if (use_feat_dim < 0) use_feat_dim = 0;
            auto err_alloc = va::analyzer::cudaops::ocsort_alloc_state(
                gpu_state_, max_tracks_, use_feat_dim);
            if (err_alloc != cudaSuccess) {
                return false;
            }
            gpu_state_ready_ = true;
        }
        auto err = va::analyzer::cudaops::ocsort_match_and_update(
            gdet,
            d_feats,
            gpu_state_,
            iou_thresh_,
            feat_alpha_,
            w_iou_,
            w_reid_,
            max_missed_,
            1,
            static_cast<cudaStream_t>(ctx.stream));
        if (err != cudaSuccess) return false;
    }

    // 构造 GPU 轨迹 ROI 视图：直接引用 GPU 状态中的轨迹 boxes / ids
    if (!gpu_state_ready_) return false;
    int h_count = 0;
    if (gpu_state_.d_track_count) {
        if (cudaMemcpy(&h_count,
                       gpu_state_.d_track_count,
                       sizeof(int32_t),
                       cudaMemcpyDeviceToHost) != cudaSuccess) {
            return false;
        }
    }
    if (h_count < 0) h_count = 0;
    va::analyzer::multistage::GpuRoiBuffer buf;
    buf.d_boxes  = gpu_state_.d_track_boxes;
    buf.d_scores = nullptr;
    buf.d_cls    = gpu_state_.d_track_ids;
    buf.count    = h_count;
    p.gpu_rois[out_rois_key_] = buf;
    // GPU 路径下不再填充 CPU rois[out_rois_key_]，交由 overlay.cuda 直接消费 gpu_rois
    p.rois.erase(out_rois_key_);
    return true;
}

#endif // USE_CUDA

} } } // namespace
