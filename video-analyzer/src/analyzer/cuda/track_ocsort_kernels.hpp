#pragma once

#include <cstdint>

#if defined(__CUDACC__) || defined(__CUDA_ARCH__) || defined(USE_CUDA)
#include <cuda_runtime.h>
#else
typedef void* cudaStream_t;
#endif

#include "analyzer/multistage/interfaces.hpp"

namespace va::analyzer::cudaops {

// GPU-side persistent OCSORT tracker state.
struct OcsortGpuState {
    float*   d_track_boxes {nullptr};    // [T_max,4] (x1,y1,x2,y2)
    float*   d_track_feats {nullptr};    // [T_max,D] L2-normalized feature per track
    int32_t* d_track_ids   {nullptr};    // [T_max]   track id
    int32_t* d_track_missed{nullptr};    // [T_max]   missed frame count
    int32_t* d_track_age   {nullptr};    // [T_max]   track age in frames
    int32_t* d_track_hit_streak{nullptr}; // [T_max]  consecutive hit count
    uint8_t* d_track_has_feat{nullptr};  // [T_max]   0/1 whether feat is valid
    float*   d_track_vel   {nullptr};    // [T_max,2] simple velocity (vx,vy) per track
    // Kalman filter state（7 维：x,y,s,r, vx,vy,vs），完全在 GPU 侧维护
    float*   d_kf_x        {nullptr};    // [T_max,7] 状态向量
    float*   d_kf_P        {nullptr};    // [T_max,7*7] 协方差矩阵（行主序）
    int32_t* d_track_count {nullptr};    // [1]       current active track count T
    int32_t* d_next_id     {nullptr};    // [1]       next track id to allocate
    // 仅用于渲染输出的视图缓冲：每帧由内核根据 hit/missed/min_hits 过滤填充
    float*   d_view_boxes  {nullptr};    // [T_max,4] (x1,y1,x2,y2) visible tracks
    int32_t* d_view_ids    {nullptr};    // [T_max]   visible track ids
    int32_t* d_view_count  {nullptr};    // [1]       visible track count

    // 匈牙利/多阶段匹配的 GPU 侧 scratch 缓冲（避免在 kernel 内使用大栈数组导致大量 local memory）
    float*   d_cost_ext    {nullptr};    // [H_max,H_max] 匈牙利扩展代价矩阵
    float*   d_hung_u      {nullptr};    // [H_max+1]
    float*   d_hung_v      {nullptr};    // [H_max+1]
    int32_t* d_hung_p      {nullptr};    // [H_max+1]
    int32_t* d_hung_way    {nullptr};    // [H_max+1]
    float*   d_hung_minv   {nullptr};    // [H_max+1]
    int8_t*  d_hung_used   {nullptr};    // [H_max+1]

    float*   d_cost_buf    {nullptr};    // [T_max,D_max] 多阶段匹配的代价矩阵缓冲
    int32_t* d_match_row_to_col {nullptr}; // [T_max] 匈牙利输出：轨迹 -> 检测
    int32_t  max_tracks {0};
    int32_t  feat_dim   {0};
};

// Allocate device buffers for OCSORT state.
// feat_dim 可以为 0（仅 IoU 匹配）。
cudaError_t ocsort_alloc_state(OcsortGpuState& state, int max_tracks, int feat_dim);

// Free device buffers in state (no-op if未初始化)。
void ocsort_free_state(OcsortGpuState& state);

// Run one OCSORT update on GPU:
// - det_rois: 当前帧检测框（来自 NMS 的 GPU 视图）。
// - d_det_feats: 可选 ReID 特征 [N,D]（GPU tensor，或 nullptr 表示仅 IoU）。
// - state: 持久化轨迹状态，在本函数内完成匹配、EMA 与轨迹增删。
// - 输出：state 中的 d_track_boxes/d_track_ids/d_track_count 更新，可直接作为 rois:track 使用。
cudaError_t ocsort_match_and_update(
    const va::analyzer::multistage::GpuRoiBuffer& det_rois,
    const float* d_det_feats,   // [N,D] on device or nullptr
    OcsortGpuState& state,
    float iou_thresh,
    float feat_alpha,
    float w_iou,
    float w_reid,
    float det_thresh,
    float low_score_thresh,
    int   use_byte,
    int   embedding_off,
    int   aw_off,
    float w_assoc_emb,
    float alpha_fixed_emb,
    float aw_param,
    int   max_missed,
    int   min_hits,
    int   frame_index,
    int   next_id_base,         // 初始 id 基准（>0 时在首次使用时生效，其后由 GPU 自增维护）
    cudaStream_t stream);

} // namespace va::analyzer::cudaops
