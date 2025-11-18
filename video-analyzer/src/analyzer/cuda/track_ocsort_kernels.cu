#include "analyzer/cuda/track_ocsort_kernels.hpp"

namespace va::analyzer::cudaops {

#if defined(USE_CUDA)

static inline cudaError_t alloc_zero(void** ptr, size_t bytes) {
    *ptr = nullptr;
    if (bytes == 0) return cudaSuccess;
    cudaError_t err = cudaMalloc(ptr, bytes);
    if (err != cudaSuccess) return err;
    return cudaMemset(*ptr, 0, bytes);
}

cudaError_t ocsort_alloc_state(OcsortGpuState& state, int max_tracks, int feat_dim) {
    if (max_tracks <= 0) return cudaErrorInvalidValue;
    if (feat_dim < 0) feat_dim = 0;
    // 清理旧状态（如果有）
    ocsort_free_state(state);

    state.max_tracks = max_tracks;
    state.feat_dim   = feat_dim;

    cudaError_t err = cudaSuccess;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_boxes),
                          static_cast<size_t>(max_tracks) * 4u * sizeof(float))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_feats),
                          static_cast<size_t>(max_tracks) * static_cast<size_t>(feat_dim) * sizeof(float))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_ids),
                          static_cast<size_t>(max_tracks) * sizeof(int32_t))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_missed),
                          static_cast<size_t>(max_tracks) * sizeof(int32_t))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_has_feat),
                          static_cast<size_t>(max_tracks) * sizeof(uint8_t))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_vel),
                          static_cast<size_t>(max_tracks) * 2u * sizeof(float))) != cudaSuccess) return err;
    // Kalman 状态：x[7] + P[7x7] per track
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_kf_x),
                          static_cast<size_t>(max_tracks) * 7u * sizeof(float))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_kf_P),
                          static_cast<size_t>(max_tracks) * 7u * 7u * sizeof(float))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_track_count),
                          sizeof(int32_t))) != cudaSuccess) return err;
    if ((err = alloc_zero(reinterpret_cast<void**>(&state.d_next_id),
                          sizeof(int32_t))) != cudaSuccess) return err;
    return cudaSuccess;
}

void ocsort_free_state(OcsortGpuState& state) {
    auto safe_free = [](void*& p) {
        if (p) cudaFree(p);
        p = nullptr;
    };
    safe_free(reinterpret_cast<void*&>(state.d_track_boxes));
    safe_free(reinterpret_cast<void*&>(state.d_track_feats));
    safe_free(reinterpret_cast<void*&>(state.d_track_ids));
    safe_free(reinterpret_cast<void*&>(state.d_track_missed));
    safe_free(reinterpret_cast<void*&>(state.d_track_has_feat));
    safe_free(reinterpret_cast<void*&>(state.d_track_vel));
    safe_free(reinterpret_cast<void*&>(state.d_kf_x));
    safe_free(reinterpret_cast<void*&>(state.d_kf_P));
    safe_free(reinterpret_cast<void*&>(state.d_track_count));
    safe_free(reinterpret_cast<void*&>(state.d_next_id));
    state.max_tracks = 0;
    state.feat_dim   = 0;
}

// --- device helpers ---

constexpr int KF_DIM_X = 7;
constexpr int KF_DIM_Z = 4;

__device__ inline float iou_yxyx(const float* a, const float* b) {
    float x1 = fmaxf(a[0], b[0]);
    float y1 = fmaxf(a[1], b[1]);
    float x2 = fminf(a[2], b[2]);
    float y2 = fminf(a[3], b[3]);
    float w = fmaxf(0.0f, x2 - x1);
    float h = fmaxf(0.0f, y2 - y1);
    float inter = w * h;
    if (inter <= 0.0f) return 0.0f;
    float areaA = fmaxf(0.0f, a[2] - a[0]) * fmaxf(0.0f, a[3] - a[1]);
    float areaB = fmaxf(0.0f, b[2] - b[0]) * fmaxf(0.0f, b[3] - b[1]);
    float uni = areaA + areaB - inter;
    if (uni <= 0.0f) return 0.0f;
    return inter / uni;
}

__device__ inline float cosine_normed(const float* a, const float* b, int D) {
    if (!a || !b || D <= 0) return 0.0f;
    double dot = 0.0;
    double nb = 0.0;
    for (int i = 0; i < D; ++i) {
        double va = static_cast<double>(a[i]);
        double vb = static_cast<double>(b[i]);
        dot += va * vb;
        nb  += vb * vb;
    }
    if (nb <= 1e-12) return 0.0f;
    nb = std::sqrt(nb);
    double denom = nb; // a 已假定为单位向量
    if (denom <= 1e-12) return 0.0f;
    return static_cast<float>(dot / denom);
}

__device__ inline void l2_normalize(float* v, int D) {
    double ss = 0.0;
    for (int i = 0; i < D; ++i) {
        double x = static_cast<double>(v[i]);
        ss += x * x;
    }
    if (ss <= 1e-12) return;
    double inv = 1.0 / std::sqrt(ss);
    for (int i = 0; i < D; ++i) {
        v[i] = static_cast<float>(static_cast<double>(v[i]) * inv);
    }
}

// 将 [x1,y1,x2,y2] 转为 Kalman 观测 z=[cx,cy,s,r]
__device__ inline void bbox_to_z(const float* bbox, float* z_out4) {
    float w = bbox[2] - bbox[0];
    float h = bbox[3] - bbox[1];
    float x = bbox[0] + w * 0.5f;
    float y = bbox[1] + h * 0.5f;
    float s = w * h;
    float r = (h > 0.0f) ? (w / h) : 0.0f;
    z_out4[0] = x;
    z_out4[1] = y;
    z_out4[2] = s;
    z_out4[3] = r;
}

// 将 Kalman 状态 x=[cx,cy,s,r,...] 转为 bbox [x1,y1,x2,y2]
__device__ inline void x_to_bbox(const float* x, float* bbox_out4) {
    float cx = x[0];
    float cy = x[1];
    float s  = x[2];
    float r  = x[3];
    float w = sqrtf(fmaxf(s * r, 0.0f));
    float h = (w > 0.0f) ? (s / w) : 0.0f;
    bbox_out4[0] = cx - 0.5f * w;
    bbox_out4[1] = cy - 0.5f * h;
    bbox_out4[2] = cx + 0.5f * w;
    bbox_out4[3] = cy + 0.5f * h;
}

// Kalman 预测：x=F x, P=F P F^T + Q
__device__ inline void kf_predict(float* x, float* P) {
    // F 矩阵（7x7）
    const float F[KF_DIM_X * KF_DIM_X] = {
        1,0,0,0,1,0,0,
        0,1,0,0,0,1,0,
        0,0,1,0,0,0,1,
        0,0,0,1,0,0,0,
        0,0,0,0,1,0,0,
        0,0,0,0,0,1,0,
        0,0,0,0,0,0,1
    };
    // Q 简化为对角阵，增强速度和 scale 维度的不确定性
    float Q[KF_DIM_X * KF_DIM_X] = {0};
    for (int i = 0; i < KF_DIM_X; ++i) {
        float v = 1.0f;
        if (i >= 4) v = 0.01f;
        Q[i * KF_DIM_X + i] = v;
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

// 4x4 矩阵求逆（简单 Gauss-Jordan）
__device__ inline bool invert4x4(const float* A, float* Ainv) {
    float m[4][8];
    for (int i = 0; i < 4; ++i) {
        for (int j = 0; j < 4; ++j) m[i][j] = A[i * 4 + j];
        for (int j = 0; j < 4; ++j) m[i][4 + j] = (i == j) ? 1.0f : 0.0f;
    }
    for (int col = 0; col < 4; ++col) {
        int pivot = col;
        float maxv = fabsf(m[col][col]);
        for (int r = col + 1; r < 4; ++r) {
            float v = fabsf(m[r][col]);
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

// Kalman 更新：x,P 与观测 z=[cx,cy,s,r]
__device__ inline void kf_update(float* x, float* P, const float* z) {
    // H: 4x7
    const float H[KF_DIM_Z * KF_DIM_X] = {
        1,0,0,0,0,0,0,
        0,1,0,0,0,0,0,
        0,0,1,0,0,0,0,
        0,0,0,1,0,0,0
    };
    // R: 4x4，与 Deep-OC-SORT 类似，对 s,r 维加大噪声
    float R[KF_DIM_Z * KF_DIM_Z] = {
        1,0,0,0,
        0,1,0,0,
        0,0,10,0,
        0,0,0,10
    };
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

    // S = H P H^T + R
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
    if (!invert4x4(S, S_inv)) {
        return;
    }

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

// 单线程 kernel，在 GPU 上完成一帧内的 OCSORT 更新：
// - 计算 IoU (+ 可选 ReID) 匹配得分；
// - 贪心匹配已有轨迹与检测；
// - 为未匹配检测创建新轨迹；
// - 对未匹配轨迹增加 missed，并按 max_missed 压缩轨迹数组。
__global__ void k_ocsort_step(
    va::analyzer::multistage::GpuRoiBuffer det_rois,
    const float* d_det_feats,
    OcsortGpuState state,
    float iou_thresh,
    float feat_alpha,
    float w_iou,
    float w_reid,
    int   max_missed,
    int   next_id_base)
{
    if (blockIdx.x != 0 || threadIdx.x != 0) return;

    const int MAX_TRACKS = 512;
    const int MAX_DETS   = 512;

    const int N_raw = det_rois.count;
    int N = N_raw < 0 ? 0 : N_raw;
    if (N > MAX_DETS) N = MAX_DETS;

    int T = 0;
    if (state.d_track_count) {
        T = *state.d_track_count;
        if (T < 0) T = 0;
        if (T > state.max_tracks) T = state.max_tracks;
        if (T > MAX_TRACKS) T = MAX_TRACKS;
    }
    const int D = state.feat_dim;

    // 如果没有任何轨迹且没有检测，直接返回
    if (T == 0 && N == 0) return;

    // Kalman 预测：对当前所有轨迹执行一次预测，将结果写回 d_track_boxes 作为预测框
    if (state.d_kf_x && state.d_kf_P && state.d_track_boxes) {
        for (int t = 0; t < T; ++t) {
            float* x = state.d_kf_x + t * KF_DIM_X;
            float* P = state.d_kf_P + t * KF_DIM_X * KF_DIM_X;
            kf_predict(x, P);
            float* tb = state.d_track_boxes + t * 4;
            x_to_bbox(x, tb);
        }
    }

    // 初始化下一轨迹 ID（只在首次调用时使用 next_id_base 进行初始化）
    int next_id = 1;
    if (state.d_next_id) {
        next_id = *state.d_next_id;
        if (next_id <= 0) {
            next_id = (next_id_base > 0) ? next_id_base : 1;
        }
    } else {
        next_id = (next_id_base > 0) ? next_id_base : 1;
    }

    // 无检测时，仅执行 missed++ 与压缩
    if (N == 0) {
        if (state.d_track_missed && state.d_track_ids && state.d_track_boxes) {
            int dst = 0;
            for (int t = 0; t < T; ++t) {
                int missed = state.d_track_missed[t] + 1;
                if (missed > max_missed) continue;
                if (dst != t) {
                    // move track t -> dst
                    state.d_track_ids[dst]    = state.d_track_ids[t];
                    state.d_track_missed[dst] = missed;
                    if (state.d_track_has_feat && state.d_track_feats && D > 0) {
                        state.d_track_has_feat[dst] = state.d_track_has_feat[t];
                        float* dst_feat = state.d_track_feats + dst * D;
                        const float* src_feat = state.d_track_feats + t * D;
                        for (int k = 0; k < D; ++k) dst_feat[k] = src_feat[k];
                    }
                    float* dst_box = state.d_track_boxes + dst * 4;
                    const float* src_box = state.d_track_boxes + t * 4;
                    dst_box[0] = src_box[0];
                    dst_box[1] = src_box[1];
                    dst_box[2] = src_box[2];
                    dst_box[3] = src_box[3];
                    if (state.d_track_vel) {
                        float* dst_vel = state.d_track_vel + dst * 2;
                        const float* src_vel = state.d_track_vel + t * 2;
                        dst_vel[0] = src_vel[0];
                        dst_vel[1] = src_vel[1];
                    }
                } else {
                    state.d_track_missed[dst] = missed;
                }
                ++dst;
            }
            if (state.d_track_count) *state.d_track_count = dst;
        }
        if (state.d_next_id) *state.d_next_id = next_id;
        return;
    }

    // 标记数组：记录哪些轨迹/检测已匹配
    uint8_t track_used[MAX_TRACKS];
    uint8_t det_used[MAX_DETS];
    for (int t = 0; t < T; ++t) track_used[t] = 0;
    for (int i = 0; i < N; ++i) det_used[i] = 0;

    // 贪心匹配：每次寻找 score 最高的 (track, det) 对
    while (true) {
        float best_score = 0.0f;
        int   best_t = -1;
        int   best_d = -1;

        for (int t = 0; t < T; ++t) {
            if (track_used[t]) continue;
            const float* tb = state.d_track_boxes ? (state.d_track_boxes + t * 4) : nullptr;
            if (!tb) break;
            // tb 当前已为 Kalman 预测后的框
            // 轨迹速度方向（用于角度一致性代价）
            float vel_nx = 0.0f, vel_ny = 0.0f;
            if (state.d_track_vel) {
                float vx = state.d_track_vel[t * 2 + 0];
                float vy = state.d_track_vel[t * 2 + 1];
                float n = sqrtf(vx * vx + vy * vy);
                if (n > 1e-6f) {
                    vel_nx = vx / n;
                    vel_ny = vy / n;
                }
            }
            float tcx = 0.5f * (tb[0] + tb[2]);
            float tcy = 0.5f * (tb[1] + tb[3]);
            for (int d = 0; d < N; ++d) {
                if (det_used[d]) continue;
                const float* db = det_rois.d_boxes ? (det_rois.d_boxes + d * 4) : nullptr;
                if (!db) break;
                float v_iou = iou_yxyx(tb, db);
                if (v_iou < iou_thresh) continue;

                float v_reid = 0.0f;
                if (D > 0 && d_det_feats && state.d_track_feats && state.d_track_has_feat) {
                    if (state.d_track_has_feat[t]) {
                        const float* tf = state.d_track_feats + t * D;
                        const float* df = d_det_feats + d * D;
                        v_reid = cosine_normed(tf, df, D);
                    }
                }

                // 角度一致性代价：检测方向与轨迹速度方向的一致性
                float dcx = 0.5f * (db[0] + db[2]);
                float dcy = 0.5f * (db[1] + db[3]);
                float dx = dcx - tcx;
                float dy = dcy - tcy;
                float dn = sqrtf(dx * dx + dy * dy);
                float angle_score = 0.0f;
                if (dn > 1e-6f && (vel_nx != 0.0f || vel_ny != 0.0f)) {
                    float dirx = dx / dn;
                    float diry = dy / dn;
                    float cosv = vel_nx * dirx + vel_ny * diry;
                    if (cosv > 1.0f) cosv = 1.0f;
                    if (cosv < -1.0f) cosv = -1.0f;
                    float ang = acosf(cosv);
                    // 按 OC-SORT 思路，将 [-pi/2,pi/2] 映射到 [0,1]
                    const float pi = 3.14159265358979323846f;
                    angle_score = (0.5f * pi - fabsf(ang)) / pi;
                    if (angle_score < 0.0f) angle_score = 0.0f;
                }
                const float inertia = 0.2f; // 可视为 Deep-OC-SORT 中的 vdc_weight

                float score = w_iou * v_iou + w_reid * v_reid + inertia * angle_score;
                if (score > best_score) {
                    best_score = score;
                    best_t = t;
                    best_d = d;
                }
            }
        }

        if (best_t < 0 || best_d < 0) break;

        // 接受匹配：更新轨迹 box / feat / missed
        track_used[best_t] = 1;
        det_used[best_d] = 1;

        if (state.d_track_boxes && det_rois.d_boxes) {
            const float* db = det_rois.d_boxes + best_d * 4;
            // 先更新 Kalman 状态，再从状态推回 bbox
            if (state.d_kf_x && state.d_kf_P) {
                float* x = state.d_kf_x + best_t * KF_DIM_X;
                float* P = state.d_kf_P + best_t * KF_DIM_X * KF_DIM_X;
                float z[4];
                bbox_to_z(db, z);
                kf_update(x, P, z);
                float* tb = state.d_track_boxes + best_t * 4;
                x_to_bbox(x, tb);
            } else {
                float* tb = state.d_track_boxes + best_t * 4;
                tb[0] = db[0];
                tb[1] = db[1];
                tb[2] = db[2];
                tb[3] = db[3];
            }
        }
        if (state.d_track_missed) {
            state.d_track_missed[best_t] = 0;
        }

        if (D > 0 && d_det_feats && state.d_track_feats) {
            float* tf = state.d_track_feats + best_t * D;
            const float* df = d_det_feats + best_d * D;
            if (state.d_track_has_feat && state.d_track_has_feat[best_t]) {
                float a = feat_alpha;
                float b = 1.0f - a;
                for (int k = 0; k < D; ++k) {
                    tf[k] = a * tf[k] + b * df[k];
                }
            } else {
                for (int k = 0; k < D; ++k) tf[k] = df[k];
            }
            l2_normalize(tf, D);
            if (state.d_track_has_feat) state.d_track_has_feat[best_t] = 1;
        }
    }

    // 为未匹配检测创建新轨迹
    for (int d = 0; d < N; ++d) {
        if (det_used[d]) continue;
        if (T >= state.max_tracks || T >= MAX_TRACKS) break;
        int t = T++;
        if (state.d_track_boxes && det_rois.d_boxes) {
            float* tb = state.d_track_boxes + t * 4;
            const float* db = det_rois.d_boxes + d * 4;
            tb[0] = db[0];
            tb[1] = db[1];
            tb[2] = db[2];
            tb[3] = db[3];
            // 初始化 Kalman 状态
            if (state.d_kf_x && state.d_kf_P) {
                float* x = state.d_kf_x + t * KF_DIM_X;
                float* P = state.d_kf_P + t * KF_DIM_X * KF_DIM_X;
                float z[4];
                bbox_to_z(db, z);
                // x0 = [cx,cy,s,r, 0,0,0]
                x[0] = z[0];
                x[1] = z[1];
                x[2] = z[2];
                x[3] = z[3];
                x[4] = 0.0f;
                x[5] = 0.0f;
                x[6] = 0.0f;
                // P0：观测部分 10，速度部分 10000
                for (int i = 0; i < KF_DIM_X * KF_DIM_X; ++i) P[i] = 0.0f;
                for (int i = 0; i < KF_DIM_X; ++i) {
                    float v = (i < 4) ? 10.0f : 10000.0f;
                    P[i * KF_DIM_X + i] = v;
                }
            }
        }
        if (state.d_track_missed) {
            state.d_track_missed[t] = 0;
        }
        if (state.d_track_ids) {
            state.d_track_ids[t] = next_id++;
        }
        if (D > 0 && d_det_feats && state.d_track_feats) {
            float* tf = state.d_track_feats + t * D;
            const float* df = d_det_feats + d * D;
            for (int k = 0; k < D; ++k) tf[k] = df[k];
            l2_normalize(tf, D);
            if (state.d_track_has_feat) state.d_track_has_feat[t] = 1;
        } else {
            if (state.d_track_has_feat) state.d_track_has_feat[t] = 0;
        }
        if (state.d_track_vel) {
            float* vel = state.d_track_vel + t * 2;
            vel[0] = 0.0f;
            vel[1] = 0.0f;
        }
        track_used[t] = 1; // 新轨迹视为本帧已更新
    }

    // 未匹配轨迹 missed++
    if (state.d_track_missed) {
        for (int t = 0; t < T; ++t) {
            if (!track_used[t]) {
                state.d_track_missed[t] += 1;
            }
        }
    }

    // 压缩：删除 missed 过大的轨迹
    int dst = 0;
    for (int t = 0; t < T; ++t) {
        int missed = state.d_track_missed ? state.d_track_missed[t] : 0;
        if (missed > max_missed) continue;
        if (dst != t) {
            if (state.d_track_ids)    state.d_track_ids[dst]    = state.d_track_ids[t];
            if (state.d_track_missed) state.d_track_missed[dst] = missed;
            if (state.d_track_has_feat && state.d_track_feats && D > 0) {
                state.d_track_has_feat[dst] = state.d_track_has_feat[t];
                float* dst_feat = state.d_track_feats + dst * D;
                const float* src_feat = state.d_track_feats + t * D;
                for (int k = 0; k < D; ++k) dst_feat[k] = src_feat[k];
            }
            if (state.d_track_boxes) {
                float* dst_box = state.d_track_boxes + dst * 4;
                const float* src_box = state.d_track_boxes + t * 4;
                dst_box[0] = src_box[0];
                dst_box[1] = src_box[1];
                dst_box[2] = src_box[2];
                dst_box[3] = src_box[3];
            }
            if (state.d_track_vel) {
                float* dst_vel = state.d_track_vel + dst * 2;
                const float* src_vel = state.d_track_vel + t * 2;
                dst_vel[0] = src_vel[0];
                dst_vel[1] = src_vel[1];
            }
        }
        ++dst;
    }
    if (state.d_track_count) *state.d_track_count = dst;
    if (state.d_next_id) *state.d_next_id = next_id;
}

cudaError_t ocsort_match_and_update(
    const va::analyzer::multistage::GpuRoiBuffer& det_rois,
    const float* d_det_feats,
    OcsortGpuState& state,
    float iou_thresh,
    float feat_alpha,
    float w_iou,
    float w_reid,
    int   max_missed,
    int   next_id_base,
    cudaStream_t stream)
{
    if (!state.d_track_boxes || !state.d_track_ids || !state.d_track_missed || !state.d_track_count) {
        return cudaErrorNotReady;
    }
    // 在单线程 kernel 中完成一次更新；由于数据量有限，这种实现足够。
    k_ocsort_step<<<1, 1, 0, stream>>>(det_rois, d_det_feats, state,
                                       iou_thresh, feat_alpha, w_iou, w_reid,
                                       max_missed, next_id_base);
    return cudaGetLastError();
}

#else  // !USE_CUDA

cudaError_t ocsort_alloc_state(OcsortGpuState& state, int /*max_tracks*/, int /*feat_dim*/) {
    state.max_tracks = 0;
    state.feat_dim   = 0;
    return cudaErrorNotSupported;
}

void ocsort_free_state(OcsortGpuState& state) {
    (void)state;
}

cudaError_t ocsort_match_and_update(
    const va::analyzer::multistage::GpuRoiBuffer& /*det_rois*/,
    const float* /*d_det_feats*/,
    OcsortGpuState& /*state*/,
    float /*iou_thresh*/,
    float /*feat_alpha*/,
    float /*w_iou*/,
    float /*w_reid*/,
    int   /*max_missed*/,
    int   /*next_id_base*/,
    cudaStream_t /*stream*/)
{
    return cudaErrorNotSupported;
}

#endif // USE_CUDA

} // namespace va::analyzer::cudaops
