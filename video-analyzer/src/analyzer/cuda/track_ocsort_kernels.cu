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
    safe_free(reinterpret_cast<void*&>(state.d_track_count));
    safe_free(reinterpret_cast<void*&>(state.d_next_id));
    state.max_tracks = 0;
    state.feat_dim   = 0;
}

// --- device helpers ---

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
                float score = w_iou * v_iou + w_reid * v_reid;
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
            float* tb = state.d_track_boxes + best_t * 4;
            const float* db = det_rois.d_boxes + best_d * 4;
            tb[0] = db[0];
            tb[1] = db[1];
            tb[2] = db[2];
            tb[3] = db[3];
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

