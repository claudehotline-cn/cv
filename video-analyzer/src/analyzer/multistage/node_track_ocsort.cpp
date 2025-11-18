#include "analyzer/multistage/node_track_ocsort.hpp"
#include "analyzer/multistage/nodes_common.hpp"
#include "core/logger.hpp"
#include "analyzer/logging_util.hpp"
#if defined(USE_CUDA)
#include <cuda_runtime.h>
#endif
#include <algorithm>
#include <cmath>
#include <opencv2/imgproc.hpp>
#include <opencv2/video/tracking.hpp>
#include <opencv2/calib3d.hpp>

using va::analyzer::multistage::util::get_or_float;
using va::analyzer::multistage::util::get_or_int;

namespace {

// 简化版匈牙利算法（Kuhn-Munkres），用于小规模代价矩阵的最小化匹配。
// 约定：cost 矩阵为行优先，行=轨迹，列=检测，维度 row_count x col_count。
// 返回一组 (row_index, col_index) 匹配对。
std::vector<std::pair<int,int>> hungarian_minimize(const std::vector<float>& cost,
                                                   int row_count,
                                                   int col_count)
{
    const int n = std::max(row_count, col_count);
    if (row_count == 0 || col_count == 0) return {};

    // 扩展为 n x n 矩阵，缺省填 0
    std::vector<float> cost_ext(n * n, 0.0f);
    for (int r = 0; r < row_count; ++r) {
        for (int c = 0; c < col_count; ++c) {
            cost_ext[r * n + c] = cost[r * col_count + c];
        }
    }

    std::vector<float> u(n + 1, 0.0f), v(n + 1, 0.0f);
    std::vector<int> p(n + 1, 0), way(n + 1, 0);
    for (int i = 1; i <= n; ++i) {
        p[0] = i;
        int j0 = 0;
        std::vector<float> minv(n + 1, std::numeric_limits<float>::infinity());
        std::vector<char> used(n + 1, 0);
        do {
            used[j0] = 1;
            int i0 = p[j0];
            float delta = std::numeric_limits<float>::infinity();
            int j1 = 0;
            for (int j = 1; j <= n; ++j) {
                if (used[j]) continue;
                float cur = cost_ext[(i0 - 1) * n + (j - 1)] - u[i0] - v[j];
                if (cur < minv[j]) {
                    minv[j] = cur;
                    way[j] = j0;
                }
                if (minv[j] < delta) {
                    delta = minv[j];
                    j1 = j;
                }
            }
            for (int j = 0; j <= n; ++j) {
                if (used[j]) {
                    u[p[j]] += delta;
                    v[j] -= delta;
                } else {
                    minv[j] -= delta;
                }
            }
            j0 = j1;
        } while (p[j0] != 0);
        do {
            int j1 = way[j0];
            p[j0] = p[j1];
            j0 = j1;
        } while (j0);
    }

    std::vector<std::pair<int,int>> result;
    result.reserve(std::min(row_count, col_count));
    std::vector<int> match_row_to_col(row_count, -1);
    for (int j = 1; j <= n; ++j) {
        int i = p[j];
        if (i <= row_count && j <= col_count) {
            match_row_to_col[i - 1] = j - 1;
        }
    }
    for (int r = 0; r < row_count; ++r) {
        if (match_row_to_col[r] >= 0) {
            result.emplace_back(r, match_row_to_col[r]);
        }
    }
    return result;
}

// --- Kalman filter (CPU) helpers: 7D state, 4D measurement ---

using Roi = va::analyzer::multistage::Roi;
using CmcState = va::analyzer::multistage::CmcState;

constexpr int KF_DIM_X = 7;
constexpr int KF_DIM_Z = 4;

inline void kf_bbox_to_z(const Roi& b, float z[4]) {
    const float w = b.x2 - b.x1;
    const float h = b.y2 - b.y1;
    const float cx = b.x1 + w * 0.5f;
    const float cy = b.y1 + h * 0.5f;
    const float s  = w * h;
    const float r  = (h > 0.0f) ? (w / h) : 0.0f;
    z[0] = cx;
    z[1] = cy;
    z[2] = s;
    z[3] = r;
}

inline void kf_x_to_bbox(const float x[7], Roi& b) {
    const float cx = x[0];
    const float cy = x[1];
    const float s  = x[2];
    const float r  = x[3];
    const float w = std::sqrt(std::max(s * r, 0.0f));
    const float h = (w > 0.0f) ? (s / w) : 0.0f;
    b.x1 = cx - 0.5f * w;
    b.y1 = cy - 0.5f * h;
    b.x2 = cx + 0.5f * w;
    b.y2 = cy + 0.5f * h;
}

inline void kf_init_from_bbox(float x[7], float P[49], bool& has_kf, const Roi& b) {
    float z[4];
    kf_bbox_to_z(b, z);
    x[0] = z[0];
    x[1] = z[1];
    x[2] = z[2];
    x[3] = z[3];
    x[4] = 0.0f;
    x[5] = 0.0f;
    x[6] = 0.0f;
    // P 初始：单位阵，经 P[4:,4:]*=1000 再整体 P*=10
    for (int i = 0; i < KF_DIM_X * KF_DIM_X; ++i) P[i] = 0.0f;
    for (int i = 0; i < KF_DIM_X; ++i) P[i * KF_DIM_X + i] = 1.0f;
    for (int i = 4; i < KF_DIM_X; ++i) {
        P[i * KF_DIM_X + i] *= 1000.0f;
    }
    for (int i = 0; i < KF_DIM_X * KF_DIM_X; ++i) {
        P[i] *= 10.0f;
    }
    has_kf = true;
}

inline void kf_predict(float x[7], float P[49]) {
    static const float F[KF_DIM_X * KF_DIM_X] = {
        1,0,0,0,1,0,0,
        0,1,0,0,0,1,0,
        0,0,1,0,0,0,1,
        0,0,0,1,0,0,0,
        0,0,0,0,1,0,0,
        0,0,0,0,0,1,0,
        0,0,0,0,0,0,1
    };
    // Q 初始为单位阵，其后 Q[-1,-1]*=0.01, Q[4:,4:]*=0.01
    float Q[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) Q[i * KF_DIM_X + i] = 1.0f;
    Q[(KF_DIM_X - 1) * KF_DIM_X + (KF_DIM_X - 1)] *= 0.01f;
    for (int i = 4; i < KF_DIM_X; ++i) {
        Q[i * KF_DIM_X + i] *= 0.01f;
    }
    // x' = F x
    float x_new[KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        float sum = 0.0f;
        for (int j = 0; j < KF_DIM_X; ++j) {
            sum += F[i * KF_DIM_X + j] * x[j];
        }
        x_new[i] = sum;
    }
    // P' = F P F^T + Q
    float FP[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_X; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += F[i * KF_DIM_X + k] * P[k * KF_DIM_X + j];
            }
            FP[i * KF_DIM_X + j] = sum;
        }
    }
    float P_new[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_X; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += FP[i * KF_DIM_X + k] * F[j * KF_DIM_X + k]; // F^T
            }
            P_new[i * KF_DIM_X + j] = sum + Q[i * KF_DIM_X + j];
        }
    }
    for (int i = 0; i < KF_DIM_X; ++i) x[i] = x_new[i];
    for (int i = 0; i < KF_DIM_X * KF_DIM_X; ++i) P[i] = P_new[i];
}

inline bool invert4x4(const float* A, float* Ainv) {
    float m[4][8];
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) m[i][j] = A[i * 4 + j];
        for (int j = 0; j < 4; ++j) m[i][4 + j] = (i == j) ? 1.0f : 0.0f;
    }
    for (int col = 0; col < 4; ++col) {
        int pivot = col;
        float maxv = std::fabs(m[col][col]);
        for (int r = col + 1; r < 4; ++r) {
            float v = std::fabs(m[r][col]);
            if (v > maxv) { maxv = v; pivot = r; }
        }
        if (maxv < 1e-6f) return false;
        if (pivot != col) {
            for (int c = 0; c < 8; ++c) {
                float tmp = m[col][c];
                m[col][c] = m[pivot][c];
                m[pivot][c] = tmp;
            }
        }
        float diag = m[col][col];
        for (int c = 0; c < 8; ++c) m[col][c] /= diag;
        for (int r = 0; r < 4; ++r) {
            if (r == col) continue;
            float factor = m[r][col];
            for (int c = 0; c < 8; ++c) {
                m[r][c] -= factor * m[col][c];
            }
        }
    }
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) {
            Ainv[i * 4 + j] = m[i][4 + j];
        }
    }
    return true;
}

inline void kf_update(float x[7], float P[49], const Roi& b) {
    // H: 4x7
    static const float H[KF_DIM_Z * KF_DIM_X] = {
        1,0,0,0,0,0,0,
        0,1,0,0,0,0,0,
        0,0,1,0,0,0,0,
        0,0,0,1,0,0,0
    };
    // R: 4x4，观测噪声，后两维放大 10 倍
    float R[KF_DIM_Z * KF_DIM_Z] = {
        1,0,0,0,
        0,1,0,0,
        0,0,10,0,
        0,0,0,10
    };
    float z[4];
    kf_bbox_to_z(b, z);

    // y = z - Hx
    float hx[KF_DIM_Z] = {0};
    for (int i = 0; i < KF_DIM_Z; ++i) {
        float sum = 0.0f;
        for (int j = 0; j < KF_DIM_X; ++j) {
            sum += H[i * KF_DIM_X + j] * x[j];
        }
        hx[i] = sum;
    }
    float y[KF_DIM_Z];
    for (int i = 0; i < KF_DIM_Z; ++i) y[i] = z[i] - hx[i];

    // S = HPH^T + R
    float HP[KF_DIM_Z * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_Z; ++i) {
        for (int j = 0; j < KF_DIM_X; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += H[i * KF_DIM_X + k] * P[k * KF_DIM_X + j];
            }
            HP[i * KF_DIM_X + j] = sum;
        }
    }
    float S[KF_DIM_Z * KF_DIM_Z] = {0};
    for (int i = 0; i < KF_DIM_Z; ++i) {
        for (int j = 0; j < KF_DIM_Z; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += HP[i * KF_DIM_X + k] * H[j * KF_DIM_X + k];
            }
            S[i * KF_DIM_Z + j] = sum + R[i * KF_DIM_Z + j];
        }
    }
    float S_inv[KF_DIM_Z * KF_DIM_Z];
    if (!invert4x4(S, S_inv)) return;

    // K = P H^T S^-1
    float PHt[KF_DIM_X * KF_DIM_Z] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_Z; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += P[i * KF_DIM_X + k] * H[j * KF_DIM_X + k];
            }
            PHt[i * KF_DIM_Z + j] = sum;
        }
    }
    float K[KF_DIM_X * KF_DIM_Z] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_Z; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_Z; ++k) {
                sum += PHt[i * KF_DIM_Z + k] * S_inv[k * KF_DIM_Z + j];
            }
            K[i * KF_DIM_Z + j] = sum;
        }
    }

    // x = x + K y
    float x_new[KF_DIM_X];
    for (int i = 0; i < KF_DIM_X; ++i) {
        float sum = x[i];
        for (int k = 0; k < KF_DIM_Z; ++k) {
            sum += K[i * KF_DIM_Z + k] * y[k];
        }
        x_new[i] = sum;
    }

    // P = (I - K H) P
    float I_minus_KH[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_X; ++j) {
            float kh = 0.0f;
            for (int k = 0; k < KF_DIM_Z; ++k) {
                kh += K[i * KF_DIM_Z + k] * H[k * KF_DIM_X + j];
            }
            float val = (i == j ? 1.0f : 0.0f) - kh;
            I_minus_KH[i * KF_DIM_X + j] = val;
        }
    }
    float P_new[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        for (int j = 0; j < KF_DIM_X; ++j) {
            float sum = 0.0f;
            for (int k = 0; k < KF_DIM_X; ++k) {
                sum += I_minus_KH[i * KF_DIM_X + k] * P[k * KF_DIM_X + j];
            }
            P_new[i * KF_DIM_X + j] = sum;
        }
    }
    for (int i = 0; i < KF_DIM_X; ++i) x[i] = x_new[i];
    for (int i = 0; i < KF_DIM_X * KF_DIM_X; ++i) P[i] = P_new[i];
}

// --- CMC sparse optical flow state ---
inline cv::Matx23f cmc_identity() {
    return cv::Matx23f(1.0f, 0.0f, 0.0f,
                       0.0f, 1.0f, 0.0f);
}

// 计算稀疏光流 CMC 仿射矩阵：参考 Deep-OC-SORT 的 _affine_sparse_flow
inline cv::Matx23f cmc_compute_sparse(CmcState& st,
                                      const cv::Mat& gray,
                                      const cv::Mat& mask,
                                      int min_features) {
    cv::Matx23f A = cmc_identity();
    std::vector<cv::Point2f> keypoints;
    const int max_corners = 3000;
    cv::goodFeaturesToTrack(gray, keypoints, max_corners,
                            0.01, 1.0, mask, 3, false, 0.04);
    if (keypoints.empty()) {
        st.prev_gray = gray.clone();
        st.prev_pts.clear();
        return A;
    }

    if (st.prev_gray.empty() || st.prev_pts.empty()) {
        st.prev_gray = gray.clone();
        st.prev_pts = keypoints;
        return A;
    }

    std::vector<cv::Point2f> next_pts;
    std::vector<unsigned char> status;
    std::vector<float> err;
    cv::calcOpticalFlowPyrLK(st.prev_gray, gray,
                             st.prev_pts, next_pts,
                             status, err);

    std::vector<cv::Point2f> prev_points;
    std::vector<cv::Point2f> curr_points;
    prev_points.reserve(status.size());
    curr_points.reserve(status.size());
    for (size_t i = 0; i < status.size(); ++i) {
        if (!status[i]) continue;
        prev_points.push_back(st.prev_pts[i]);
        curr_points.push_back(next_pts[i]);
    }

    if (prev_points.size() > static_cast<size_t>(min_features)) {
        cv::Mat A_mat;
        std::vector<unsigned char> inliers;
        A_mat = cv::estimateAffinePartial2D(prev_points, curr_points,
                                            inliers, cv::RANSAC);
        if (!A_mat.empty() && A_mat.rows == 2 && A_mat.cols == 3) {
            A = A_mat;
        }
    }

    st.prev_gray = gray.clone();
    st.prev_pts = std::move(keypoints);
    return A;
}

inline void cmc_apply_affine_to_box(const cv::Matx23f& A, Roi& b, int img_w, int img_h) {
    cv::Vec3f p1(b.x1, b.y1, 1.0f);
    cv::Vec3f p2(b.x2, b.y2, 1.0f);
    cv::Vec2f q1 = A * p1;
    cv::Vec2f q2 = A * p2;
    b.x1 = std::min(std::max(q1[0], 0.0f), static_cast<float>(img_w - 1));
    b.y1 = std::min(std::max(q1[1], 0.0f), static_cast<float>(img_h - 1));
    b.x2 = std::min(std::max(q2[0], 0.0f), static_cast<float>(img_w - 1));
    b.y2 = std::min(std::max(q2[1], 0.0f), static_cast<float>(img_h - 1));
}

} // anonymous namespace

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
    det_thresh_ = get_or_float(cfg, "det_thresh", 0.5f);
    min_hits_ = get_or_int(cfg, "min_hits", 3);
    delta_t_ = get_or_int(cfg, "delta_t", 3);
    w_assoc_emb_ = get_or_float(cfg, "w_assoc_emb", 0.75f);
    alpha_fixed_emb_ = get_or_float(cfg, "alpha_fixed_emb", 0.95f);
    aw_param_ = get_or_float(cfg, "aw_param", 0.5f);
    {
        auto it = cfg.find("embedding_off");
        if (it != cfg.end()) {
            const std::string& v = it->second;
            if (v == "1" || v == "true" || v == "on" || v == "yes") {
                embedding_off_ = true;
            }
        }
        it = cfg.find("aw_off");
        if (it != cfg.end()) {
            const std::string& v = it->second;
            if (v == "1" || v == "true" || v == "on" || v == "yes") {
                aw_off_ = true;
            }
        }
    }
    {
        auto it = cfg.find("use_byte");
        if (it != cfg.end()) {
            const std::string& v = it->second;
            if (v == "0" || v == "false" || v == "off" || v == "no") {
                use_byte_ = false;
            }
        }
        it = cfg.find("cmc_method");
        if (it != cfg.end()) {
            cmc_method_ = it->second;
        }
        cmc_min_features_ = get_or_int(cfg, "cmc_min_features", 10);
        cmc_off_ = (cmc_method_ == "none" || cmc_method_.empty());
    }
    max_tracks_ = get_or_int(cfg, "max_tracks", 256);
    if (max_tracks_ < 16) max_tracks_ = 16;
    if (max_tracks_ > 512) max_tracks_ = 512;
}

bool NodeTrackOcsort::open(NodeContext& ctx) {
#if defined(USE_CUDA)
    // 当前版本：匹配逻辑固定使用 CPU Deep OC-SORT，只在 GPU 上构造 rois["track"] 视图供 overlay.zero-copy 绘制
    use_gpu_ = false;
    gpu_state_ready_ = false;
    gpu_pool_ = ctx.gpu_pool;
    (void)ctx;
#else
    (void)ctx;
#endif
    if (!cmc_off_ && !cmc_state_) {
        cmc_state_ = std::make_unique<CmcState>();
    }
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
    if (gpu_boxes_mem_.ptr) {
        if (gpu_pool_) {
            gpu_pool_->release(std::move(gpu_boxes_mem_));
        } else {
            cudaFree(gpu_boxes_mem_.ptr);
        }
        gpu_boxes_mem_ = {};
    }
    if (gpu_cls_mem_.ptr) {
        if (gpu_pool_) {
            gpu_pool_->release(std::move(gpu_cls_mem_));
        } else {
            cudaFree(gpu_cls_mem_.ptr);
        }
        gpu_cls_mem_ = {};
    }
    gpu_pool_ = nullptr;
#endif
    cmc_state_.reset();
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
    // 匹配逻辑统一走 CPU Deep OC-SORT，实现更完整的匈牙利多阶段匹配
    bool ok = process_cpu(p);
    if (!ok) return false;

#if defined(USE_CUDA)
    // 若存在 GPU 上下文，为 overlay.cuda 构造 rois["track"] 的 GPU 视图（zero-copy 绘制）
    auto it = p.rois.find(out_rois_key_);
    if (it != p.rois.end() && ctx.gpu_pool && ctx.stream) {
        const auto& rois = it->second;
        const std::size_t n = rois.size();
        if (n == 0) {
            p.gpu_rois.erase(out_rois_key_);
        } else {
            va::core::GpuBufferPool* pool = ctx.gpu_pool;
            const std::size_t box_bytes = n * 4 * sizeof(float);
            const std::size_t cls_bytes = n * sizeof(int32_t);
            // 复用/扩展 GPU 缓冲区
            if (gpu_boxes_mem_.ptr && gpu_boxes_mem_.bytes < box_bytes) {
                pool->release(std::move(gpu_boxes_mem_));
                gpu_boxes_mem_ = {};
            }
            if (!gpu_boxes_mem_.ptr) {
                gpu_boxes_mem_ = pool->acquire(box_bytes);
            }
            if (gpu_cls_mem_.ptr && gpu_cls_mem_.bytes < cls_bytes) {
                pool->release(std::move(gpu_cls_mem_));
                gpu_cls_mem_ = {};
            }
            if (!gpu_cls_mem_.ptr) {
                gpu_cls_mem_ = pool->acquire(cls_bytes);
            }
            if (gpu_boxes_mem_.ptr && gpu_cls_mem_.ptr) {
                std::vector<float> host_boxes(n * 4);
                std::vector<int32_t> host_cls(n);
                for (std::size_t i = 0; i < n; ++i) {
                    const auto& b = rois[i];
                    host_boxes[i * 4 + 0] = b.x1;
                    host_boxes[i * 4 + 1] = b.y1;
                    host_boxes[i * 4 + 2] = b.x2;
                    host_boxes[i * 4 + 3] = b.y2;
                    host_cls[i] = static_cast<int32_t>(b.cls);
                }
                auto stream = static_cast<cudaStream_t>(ctx.stream);
                cudaMemcpyAsync(gpu_boxes_mem_.ptr, host_boxes.data(),
                                box_bytes, cudaMemcpyHostToDevice, stream);
                cudaMemcpyAsync(gpu_cls_mem_.ptr, host_cls.data(),
                                cls_bytes, cudaMemcpyHostToDevice, stream);
                GpuRoiBuffer buf;
                buf.d_boxes  = static_cast<float*>(gpu_boxes_mem_.ptr);
                buf.d_scores = nullptr;
                buf.d_cls    = static_cast<int32_t*>(gpu_cls_mem_.ptr);
                buf.count    = static_cast<int32_t>(n);
                p.gpu_rois[out_rois_key_] = buf;
            }
        }
    } else {
        p.gpu_rois.erase(out_rois_key_);
    }
#endif
    return true;
}

bool NodeTrackOcsort::process_cpu(Packet& p) {
    frame_count_++;

    auto it = p.rois.find(in_rois_key_);
    if (it == p.rois.end()) {
        // 没有检测框时清空输出并衰减已有轨迹
        for (auto& tr : tracks_) {
            tr.updated = false;
            tr.hit_streak = 0;
            tr.missed++;
            tr.age++;
        }
        tracks_.erase(std::remove_if(tracks_.begin(), tracks_.end(),
                                     [&](const Track& t){ return t.missed > max_missed_; }),
                      tracks_.end());
        p.rois.erase(out_rois_key_);
        return true;
    }
    const auto& dets = it->second;

    // 可选：在匹配前执行 CMC（sparse optical flow），将已有轨迹的 box / 观测历史对齐到当前帧坐标系
    if (!cmc_off_ && cmc_state_ && !tracks_.empty()) {
        const int img_w = p.frame.width;
        const int img_h = p.frame.height;
        if (img_w > 0 && img_h > 0 && !p.frame.bgr.empty()) {
            cv::Mat bgr(img_h, img_w, CV_8UC3,
                        const_cast<uint8_t*>(p.frame.bgr.data()));
            cv::Mat gray;
            cv::cvtColor(bgr, gray, cv::COLOR_BGR2GRAY);
            cv::Mat mask(gray.size(), CV_8UC1, cv::Scalar(255));
            if (!dets.empty()) {
                for (const auto& bb : dets) {
                    int x1 = std::max(0, static_cast<int>(std::floor(bb.x1)));
                    int y1 = std::max(0, static_cast<int>(std::floor(bb.y1)));
                    int x2 = std::min(img_w - 1, static_cast<int>(std::ceil(bb.x2)));
                    int y2 = std::min(img_h - 1, static_cast<int>(std::ceil(bb.y2)));
                    if (x2 > x1 && y2 > y1) {
                        cv::Rect r(x1, y1, x2 - x1, y2 - y1);
                        mask(r).setTo(0);
                    }
                }
            }
            cv::Matx23f A = cmc_identity();
            // 当前实现：sparse / sift 均走 sparse 分支，避免引入 SIFT 依赖
            A = cmc_compute_sparse(*cmc_state_, gray, mask, cmc_min_features_);
            // 将仿射矩阵应用到当前所有轨迹及其观测历史
            for (auto& tr : tracks_) {
                cmc_apply_affine_to_box(A, tr.box, img_w, img_h);
                if (tr.has_last_obs) {
                    cmc_apply_affine_to_box(A, tr.last_obs, img_w, img_h);
                }
                for (auto& kv : tr.observations) {
                    cmc_apply_affine_to_box(A, kv.second, img_w, img_h);
                }
            }
        }
    }

    // 读取 ReID 特征 [N,D]（可选），优先使用 GPU tensor 并拷贝一份到 CPU
    const float* feat_data = nullptr;
    int feat_dim = 0;
    bool have_feat = false;
    auto itf = p.tensors.find(feat_key_);
    if (itf != p.tensors.end()) {
        const auto& tv = itf->second;
        if (tv.dtype == va::core::DType::F32 && tv.shape.size() == 2) {
            const int64_t N = tv.shape[0];
            const int64_t D = tv.shape[1];
            if (N == static_cast<int64_t>(dets.size()) && D > 0) {
                if (!tv.on_gpu) {
                    // 直接使用 CPU 特征
                    feat_data = static_cast<const float*>(tv.data);
                    feat_dim = static_cast<int>(D);
                    have_feat = true;
                } else {
#if defined(USE_CUDA)
                    // 从 GPU tensor 拷贝一份到 CPU，供 Deep OC-SORT 匹配使用
                    static thread_local std::vector<float> gpu_feat_buffer;
                    const std::size_t total = static_cast<std::size_t>(N) * static_cast<std::size_t>(D);
                    gpu_feat_buffer.resize(total);
                    auto err = cudaMemcpy(gpu_feat_buffer.data(),
                                          tv.data,
                                          total * sizeof(float),
                                          cudaMemcpyDeviceToHost);
                    if (err == cudaSuccess) {
                        feat_data = gpu_feat_buffer.data();
                        feat_dim = static_cast<int>(D);
                        have_feat = true;
                    } else {
                        auto lvl = va::analyzer::logutil::log_level_for_tag("ms.track");
                        auto thr = va::analyzer::logutil::log_throttle_ms_for_tag("ms.track");
                        VA_LOG_THROTTLED(lvl, "ms.track", thr) << "cudaMemcpy ReID feats D2H failed, err=" << static_cast<int>(err);
                    }
#endif
                }
            }
        }
    }

    const size_t T = tracks_.size();
    const size_t D = dets.size();

    // 标记所有轨迹为未更新，并推进 age；若存在 Kalman 状态，先执行一次预测
    for (auto& tr : tracks_) {
        if (tr.has_kf) {
            // 防止无效 scale/s 造成发散：与 Python 中 (x[6]+x[2])<=0 的保护类似
            if ((tr.kf_x[6] + tr.kf_x[2]) <= 0.0f) {
                tr.kf_x[6] = 0.0f;
            }
            kf_predict(tr.kf_x, tr.kf_P);
        }
        tr.updated = false;
        tr.age++;
    }

    // 多阶段匹配：Stage1 使用预测框 + 速度方向一致性 + 可选 ReID，通过匈牙利算法完成全局关联；
    // Stage2 使用 IoU 与上一观测框做简单再关联。

    // 记录每个检测对应的轨迹索引（-1 表示新建）
    std::vector<int> det_to_track(D, -1);

    if (!tracks_.empty() && !dets.empty()) {
        // 将检测按分数拆分为高分/低分两组，仿照 Deep-OC-SORT 的 dets / dets_second 思路
        std::vector<int> high_det_indices;
        std::vector<int> low_det_indices;
        high_det_indices.reserve(D);
        low_det_indices.reserve(D);
        const float low_score_thresh = 0.1f;
        for (size_t di = 0; di < D; ++di) {
            float s = dets[di].score;
            if (s > det_thresh_) {
                high_det_indices.push_back(static_cast<int>(di));
            } else if (use_byte_ && s > low_score_thresh) {
                low_det_indices.push_back(static_cast<int>(di));
            }
        }

        // Stage1: 使用高分检测进行预测框 + 速度方向 + ReID 打分矩阵匹配
        std::vector<Roi> predicted_boxes(T);
    for (size_t track_index = 0; track_index < T; ++track_index) {
        const auto& track = tracks_[track_index];
        Roi predicted;
        if (track.has_kf) {
            kf_x_to_bbox(track.kf_x, predicted);
            } else {
                const auto& box = track.box;
                float width = std::max(0.0f, box.x2 - box.x1);
                float height = std::max(0.0f, box.y2 - box.y1);
                float center_x = 0.5f * (box.x1 + box.x2);
                float center_y = 0.5f * (box.y1 + box.y2);
                float predicted_cx = center_x + track.vx;
                float predicted_cy = center_y + track.vy;
                predicted.x1 = predicted_cx - 0.5f * width;
                predicted.y1 = predicted_cy - 0.5f * height;
                predicted.x2 = predicted_cx + 0.5f * width;
                predicted.y2 = predicted_cy + 0.5f * height;
            }
            predicted.score = track.box.score;
            predicted.cls = track.box.cls;
            predicted_boxes[track_index] = predicted;
        }

        // cost 矩阵：行=轨迹，列=高分检测，代价越小越好。
        const float large_cost = 1e6f;
        const size_t DH = high_det_indices.size();
        std::vector<float> cost_stage1(T * (DH ? DH : 1), large_cost);

        for (size_t track_index = 0; track_index < T; ++track_index) {
            const Roi& predicted = predicted_boxes[track_index];
            const auto& track = tracks_[track_index];
            // 轨迹速度方向（规范化为单位向量）
            float vel_nx = 0.0f;
            float vel_ny = 0.0f;
            float vel_norm = std::sqrt(track.vx * track.vx + track.vy * track.vy);
            if (vel_norm > 1e-6f) {
                vel_nx = track.vx / vel_norm;
                vel_ny = track.vy / vel_norm;
            }

            for (size_t idx = 0; idx < DH; ++idx) {
                int det_index = high_det_indices[idx];
                const Roi& det_box = dets[det_index];
                float v_iou = iou(predicted, det_box);
                if (v_iou < iou_thresh_) continue;

                // 角度一致性：基于 k_previous_obs 近似，从 K 帧前的观测到当前检测的方向，与速度方向比较
                float angle_score = 0.0f;
                if (vel_norm > 1e-6f && track.has_last_obs && !track.observations.empty()) {
                    // 选择距当前 age 最接近 age - delta_t_ 的观测
                    int target_age = track.age - delta_t_;
                    const Roi* prev_ptr = nullptr;
                    int best_dt = std::numeric_limits<int>::max();
                    for (const auto& kv : track.observations) {
                        int a = kv.first;
                        int dt = std::abs(a - target_age);
                        if (dt < best_dt) {
                            best_dt = dt;
                            prev_ptr = &kv.second;
                        }
                    }
                    if (!prev_ptr) prev_ptr = &track.last_obs;
                    if (prev_ptr) {
                        float prev_cx = 0.5f * (prev_ptr->x1 + prev_ptr->x2);
                        float prev_cy = 0.5f * (prev_ptr->y1 + prev_ptr->y2);
                        float det_cx = 0.5f * (det_box.x1 + det_box.x2);
                        float det_cy = 0.5f * (det_box.y1 + det_box.y2);
                        float dir_x = det_cx - prev_cx;
                        float dir_y = det_cy - prev_cy;
                        float dir_norm = std::sqrt(dir_x * dir_x + dir_y * dir_y);
                        if (dir_norm > 1e-6f) {
                            dir_x /= dir_norm;
                            dir_y /= dir_norm;
                            float cosv = vel_nx * dir_x + vel_ny * dir_y;
                            cosv = std::max(-1.0f, std::min(1.0f, cosv));
                            float ang = std::acos(cosv);
                            angle_score = (static_cast<float>(M_PI_2) - std::fabs(ang)) / static_cast<float>(M_PI);
                            if (angle_score < 0.0f) angle_score = 0.0f;
                        }
                    }
                }

                // 运动相似度：IoU + 角度一致性
                const float inertia = 0.2f;
                float motion_sim = w_iou_ * v_iou + inertia * angle_score;
                // 外观相似度：基于 ReID 嵌入
                float emb_sim = 0.0f;
                if (!embedding_off_ && have_feat && track.has_feat && feat_dim > 0) {
                    const float* detection_feat = feat_data + static_cast<int>(det_index) * feat_dim;
                    emb_sim = cosine(track.feat, detection_feat, feat_dim);
                }
                // 自适应权重：根据检测分数在 motion / appearance 之间插值
                float combined_sim = motion_sim;
                if (!embedding_off_) {
                    float w = w_assoc_emb_;
                    if (!aw_off_) {
                        float trust = 0.0f;
                        if (det_box.score > det_thresh_) {
                            trust = (det_box.score - det_thresh_) / (1.0f - det_thresh_);
                            if (trust < 0.0f) trust = 0.0f;
                            if (trust > 1.0f) trust = 1.0f;
                        }
                        float aw = aw_param_ * trust + (1.0f - aw_param_);
                        w = w_assoc_emb_ * aw + (1.0f - w_assoc_emb_) * (1.0f - aw);
                    }
                    if (w < 0.0f) w = 0.0f;
                    if (w > 1.0f) w = 1.0f;
                    combined_sim = w * emb_sim + (1.0f - w) * motion_sim;
                }

                if (combined_sim <= 0.0f) continue;
                float normalized_score = std::min(combined_sim, 1.0f);
                float cost_value = 1.0f - normalized_score;
                cost_stage1[track_index * (DH ? DH : 1) + idx] = cost_value;
            }
        }

        // 通过匈牙利算法求全局最小代价匹配（轨迹 x 高分检测）
        auto matches = hungarian_minimize(cost_stage1,
                                          static_cast<int>(T),
                                          static_cast<int>(DH));
        std::vector<bool> track_used(T, false);
        std::vector<bool> det_used(D, false);
        for (const auto& pair : matches) {
            int track_index = pair.first;
            int high_idx   = pair.second;
            if (track_index < 0 || track_index >= static_cast<int>(T)) continue;
            if (high_idx < 0 || high_idx >= static_cast<int>(DH)) continue;
            int det_index = high_det_indices[high_idx];
            float cost_value = cost_stage1[track_index * (DH ? DH : 1) + high_idx];
            if (cost_value >= large_cost * 0.5f) continue;
            const Roi& predicted = predicted_boxes[track_index];
            const Roi& det_box = dets[det_index];
            float v_iou = iou(predicted, det_box);
            if (v_iou < iou_thresh_) continue;

            auto& track = tracks_[track_index];
            const Roi& prev_box = track.box;
            float prev_cx = 0.5f * (prev_box.x1 + prev_box.x2);
            float prev_cy = 0.5f * (prev_box.y1 + prev_box.y2);
            float cur_cx  = 0.5f * (det_box.x1 + det_box.x2);
            float cur_cy  = 0.5f * (det_box.y1 + det_box.y2);
            track.vx = cur_cx - prev_cx;
            track.vy = cur_cy - prev_cy;
            track.box = det_box;
            track.missed = 0;
            track.updated = true;
            track.hit_streak += 1;

            if (have_feat && feat_dim > 0) {
                const float* detection_feat = feat_data + static_cast<int>(det_index) * feat_dim;
                auto& feat = track.feat;
                if (feat.size() != static_cast<size_t>(feat_dim)) {
                    feat.assign(detection_feat, detection_feat + feat_dim);
                } else {
                    // 使用 integrated OCSORT 的 dets_alpha 思路：根据检测置信度生成 EMA 系数
                    float trust = 0.0f;
                    if (det_box.score > det_thresh_) {
                        trust = (det_box.score - det_thresh_) / (1.0f - det_thresh_);
                        trust = std::max(0.0f, std::min(1.0f, trust));
                    }
                    float det_alpha = alpha_fixed_emb_ + (1.0f - alpha_fixed_emb_) * (1.0f - trust);
                    det_alpha = std::max(0.0f, std::min(1.0f, det_alpha));
                    const float beta = 1.0f - det_alpha;
                    for (int k = 0; k < feat_dim; ++k) {
                        feat[k] = det_alpha * feat[k] + beta * detection_feat[k];
                    }
                }
                l2_normalize(track.feat);
                track.has_feat = true;
            }

            // Kalman 更新
            if (track.has_kf) {
                kf_update(track.kf_x, track.kf_P, det_box);
            }

            // 更新观测历史与 last_obs，用于下一帧的 k_previous_obs 与速度方向一致性
            track.last_obs = det_box;
            track.has_last_obs = true;
            track.observations.emplace_back(track.age, det_box);
            if (track.observations.size() > static_cast<size_t>(delta_t_ + 2)) {
                track.observations.erase(track.observations.begin());
            }

            track_used[track_index] = true;
            det_used[det_index] = true;
            det_to_track[det_index] = track_index;
        }

        // Stage2: 针对未匹配轨迹和检测，基于上一观测框做 IoU 再关联（简化版 OCR）
        std::vector<int> unmatched_tracks;
        std::vector<int> unmatched_dets_high;
        unmatched_tracks.reserve(T);
        unmatched_dets_high.reserve(D);
        for (size_t track_index = 0; track_index < T; ++track_index) {
            if (!track_used[track_index]) unmatched_tracks.push_back(static_cast<int>(track_index));
        }
        for (int idx : high_det_indices) {
            if (!det_used[idx]) unmatched_dets_high.push_back(idx);
        }

        // Stage2：BYTE 风格的低分检测再关联（可配置 use_byte_）
        if (use_byte_) {
            std::vector<int> unmatched_tracks_stage2 = unmatched_tracks;
            const size_t UT = unmatched_tracks_stage2.size();
            const size_t DL = low_det_indices.size();
            if (UT > 0 && DL > 0) {
                std::vector<float> cost_stage2(UT * DL, large_cost);
                for (size_t ui = 0; ui < UT; ++ui) {
                    int track_index = unmatched_tracks_stage2[ui];
                    const Roi& predicted = predicted_boxes[track_index];
                    for (size_t lj = 0; lj < DL; ++lj) {
                        int det_index = low_det_indices[lj];
                        const Roi& det_box = dets[det_index];
                        float v_iou = iou(predicted, det_box);
                        if (v_iou < iou_thresh_) continue;
                        float cost_value = 1.0f - v_iou;
                        cost_stage2[ui * DL + lj] = cost_value;
                    }
                }
                auto matches2 = hungarian_minimize(cost_stage2,
                                                   static_cast<int>(UT),
                                                   static_cast<int>(DL));
                for (const auto& pair : matches2) {
                    int ui = pair.first;
                    int lj = pair.second;
                    if (ui < 0 || ui >= static_cast<int>(UT)) continue;
                    if (lj < 0 || lj >= static_cast<int>(DL)) continue;
                    float cost_value = cost_stage2[ui * DL + lj];
                    if (cost_value >= large_cost * 0.5f) continue;
                    int track_index = unmatched_tracks_stage2[ui];
                    int det_index = low_det_indices[lj];
                    const Roi& predicted = predicted_boxes[track_index];
                    const Roi& det_box = dets[det_index];
                    float v_iou = iou(predicted, det_box);
                    if (v_iou < iou_thresh_) continue;

                    auto& track = tracks_[track_index];
                    const Roi& prev_box = track.box;
                    float prev_cx = 0.5f * (prev_box.x1 + prev_box.x2);
                    float prev_cy = 0.5f * (prev_box.y1 + prev_box.y2);
                    float cur_cx  = 0.5f * (det_box.x1 + det_box.x2);
                    float cur_cy  = 0.5f * (det_box.y1 + det_box.y2);
                    track.vx = cur_cx - prev_cx;
                    track.vy = cur_cy - prev_cy;
                    track.box = det_box;
                    track.missed = 0;
                    track.updated = true;
                    track.hit_streak += 1;

                if (have_feat && feat_dim > 0) {
                    const float* detection_feat = feat_data + static_cast<int>(det_index) * feat_dim;
                    auto& feat = track.feat;
                    if (feat.size() != static_cast<size_t>(feat_dim)) {
                        feat.assign(detection_feat, detection_feat + feat_dim);
                    } else {
                        float trust = 0.0f;
                        if (det_box.score > det_thresh_) {
                            trust = (det_box.score - det_thresh_) / (1.0f - det_thresh_);
                            trust = std::max(0.0f, std::min(1.0f, trust));
                        }
                        float det_alpha = alpha_fixed_emb_ + (1.0f - alpha_fixed_emb_) * (1.0f - trust);
                        det_alpha = std::max(0.0f, std::min(1.0f, det_alpha));
                        const float beta = 1.0f - det_alpha;
                        for (int k = 0; k < feat_dim; ++k) {
                            feat[k] = det_alpha * feat[k] + beta * detection_feat[k];
                        }
                    }
                    l2_normalize(track.feat);
                    track.has_feat = true;
                }

                    if (!det_used[det_index]) {
                        det_used[det_index] = true;
                        det_to_track[det_index] = track_index;
                    }
                    // 更新观测历史与 last_obs
                    track.last_obs = det_box;
                    track.has_last_obs = true;
                    track.observations.emplace_back(track.age, det_box);
                    if (track.observations.size() > static_cast<size_t>(delta_t_ + 2)) {
                        track.observations.erase(track.observations.begin());
                    }
                }
            }
        }

        // Stage3: 对未匹配的轨迹和高分检测，再用当前 box 做 IoU 关联（类似 OCR rematch）
        std::vector<int> unmatched_tracks_stage3;
        std::vector<int> unmatched_dets_stage3;
        unmatched_tracks_stage3.reserve(T);
        unmatched_dets_stage3.reserve(D);
        for (size_t track_index = 0; track_index < T; ++track_index) {
            if (!tracks_[track_index].updated) {
                unmatched_tracks_stage3.push_back(static_cast<int>(track_index));
            }
        }
        for (int idx : high_det_indices) {
            if (!det_used[idx]) unmatched_dets_stage3.push_back(idx);
        }

        if (!unmatched_tracks_stage3.empty() && !unmatched_dets_stage3.empty()) {
            const size_t UT = unmatched_tracks_stage3.size();
            const size_t UD = unmatched_dets_stage3.size();
            std::vector<float> cost_stage3(UT * UD, large_cost);
            for (size_t ui = 0; ui < UT; ++ui) {
                int track_index = unmatched_tracks_stage3[ui];
                const Roi& last_box = tracks_[track_index].box;
                for (size_t uj = 0; uj < UD; ++uj) {
                    int det_index = unmatched_dets_stage3[uj];
                    const Roi& det_box = dets[det_index];
                    float v_iou = iou(last_box, det_box);
                    if (v_iou < iou_thresh_) continue;
                    float cost_value = 1.0f - v_iou;
                    cost_stage3[ui * UD + uj] = cost_value;
                }
            }
            auto matches3 = hungarian_minimize(cost_stage3,
                                               static_cast<int>(UT),
                                               static_cast<int>(UD));
            for (const auto& pair : matches3) {
                int ui = pair.first;
                int uj = pair.second;
                if (ui < 0 || ui >= static_cast<int>(UT)) continue;
                if (uj < 0 || uj >= static_cast<int>(UD)) continue;
                float cost_value = cost_stage3[ui * UD + uj];
                if (cost_value >= large_cost * 0.5f) continue;
                int track_index = unmatched_tracks_stage3[ui];
                int det_index = unmatched_dets_stage3[uj];
                const Roi& last_box = tracks_[track_index].box;
                const Roi& det_box = dets[det_index];
                float v_iou = iou(last_box, det_box);
                if (v_iou < iou_thresh_) continue;

                auto& track = tracks_[track_index];
                float prev_cx = 0.5f * (last_box.x1 + last_box.x2);
                float prev_cy = 0.5f * (last_box.y1 + last_box.y2);
                float cur_cx  = 0.5f * (det_box.x1 + det_box.x2);
                float cur_cy  = 0.5f * (det_box.y1 + det_box.y2);
                track.vx = cur_cx - prev_cx;
                track.vy = cur_cy - prev_cy;
                track.box = det_box;
                track.missed = 0;
                track.updated = true;
                track.hit_streak += 1;

                if (have_feat && feat_dim > 0) {
                    const float* detection_feat = feat_data + static_cast<int>(det_index) * feat_dim;
                    auto& feat = track.feat;
                    if (feat.size() != static_cast<size_t>(feat_dim)) {
                        feat.assign(detection_feat, detection_feat + feat_dim);
                    } else {
                        float trust = 0.0f;
                        if (det_box.score > det_thresh_) {
                            trust = (det_box.score - det_thresh_) / (1.0f - det_thresh_);
                            trust = std::max(0.0f, std::min(1.0f, trust));
                        }
                        float det_alpha = alpha_fixed_emb_ + (1.0f - alpha_fixed_emb_) * (1.0f - trust);
                        det_alpha = std::max(0.0f, std::min(1.0f, det_alpha));
                        const float beta = 1.0f - det_alpha;
                        for (int k = 0; k < feat_dim; ++k) {
                            feat[k] = det_alpha * feat[k] + beta * detection_feat[k];
                        }
                    }
                    l2_normalize(track.feat);
                    track.has_feat = true;
                }

                if (!det_used[det_index]) {
                    det_used[det_index] = true;
                    det_to_track[det_index] = track_index;
                }
                if (track.has_kf) {
                    kf_update(track.kf_x, track.kf_P, det_box);
                }
                if (track.has_kf) {
                    kf_update(track.kf_x, track.kf_P, det_box);
                }
                // 更新观测历史与 last_obs
                track.last_obs = det_box;
                track.has_last_obs = true;
                track.observations.emplace_back(track.age, det_box);
                if (track.observations.size() > static_cast<size_t>(delta_t_ + 2)) {
                    track.observations.erase(track.observations.begin());
                }
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
        tr.age = 1;
        tr.hit_streak = 1;
        tr.vx = 0.0f;
        tr.vy = 0.0f;
        kf_init_from_bbox(tr.kf_x, tr.kf_P, tr.has_kf, tr.box);
        tr.last_obs = tr.box;
        tr.has_last_obs = true;
        tr.observations.clear();
        tr.observations.emplace_back(tr.age, tr.box);
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
            tr.hit_streak = 0;
            // 对于未匹配轨迹，将几何 box 推进到预测位置，便于后续帧的重识别/再关联
            float w = std::max(0.0f, tr.box.x2 - tr.box.x1);
            float h = std::max(0.0f, tr.box.y2 - tr.box.y1);
            float cx = 0.5f * (tr.box.x1 + tr.box.x2);
            float cy = 0.5f * (tr.box.y1 + tr.box.y2);
            float pcx = cx + tr.vx;
            float pcy = cy + tr.vy;
            tr.box.x1 = pcx - 0.5f * w;
            tr.box.y1 = pcy - 0.5f * h;
            tr.box.x2 = pcx + 0.5f * w;
            tr.box.y2 = pcy + 0.5f * h;
        }
    }
    tracks_.erase(std::remove_if(tracks_.begin(), tracks_.end(),
                                 [&](const Track& t){ return t.missed > max_missed_; }),
                  tracks_.end());

    // 构造输出 ROI：沿用检测框几何与 score，将 cls 字段复用为 track_id；
    // 仅输出稳定轨迹：命中次数达到 min_hits_ 或在 warmup 帧内
    std::vector<Roi> out;
    out.reserve(D);
    for (size_t di = 0; di < D; ++di) {
        int ti = det_to_track[di];
        if (ti < 0 || ti >= (int)tracks_.size()) continue;
        const auto& tr = tracks_[ti];
        if (tr.hit_streak < min_hits_ && frame_count_ > min_hits_) continue;
        Roi b = dets[di];
        b.cls = tr.id;
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
        // 只有轨迹衰减，无新的检测框：仅更新内部状态，不再对外输出轨迹框，避免在画面上保留“幽灵”轨迹
        if (!gpu_state_ready_) {
            // 无状态且无检测时，仅清空本帧的输出 ROI
            p.gpu_rois.erase(out_rois_key_);
            p.rois.erase(out_rois_key_);
            return true;
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
        // 内部状态已更新，本帧不再输出轨迹框
        p.gpu_rois.erase(out_rois_key_);
        p.rois.erase(out_rois_key_);
        return true;
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
