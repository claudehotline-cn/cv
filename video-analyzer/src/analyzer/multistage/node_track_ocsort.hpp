#pragma once

#include "analyzer/multistage/interfaces.hpp"
#include "core/gpu_buffer_pool.hpp"
#include <unordered_map>
#include <vector>

#if defined(USE_CUDA)
#include "analyzer/cuda/track_ocsort_kernels.hpp"
#endif

namespace va { namespace analyzer { namespace multistage {

// OCSORT-style multi-object tracker node.
// - 输入：来自检测阶段的 ROI（默认为 rois["det"] / gpu_rois["det"]）。
// - 输出：跟踪后的 ROI（默认 rois["track"]/gpu_rois["track"]），其中 Box.cls 被复用为 track_id。
// - Graph 生命周期内维护状态，每条订阅管线实例拥有独立的追踪器。
//
// 配置参数（YAML params）：
//   in_rois    : string，输入 ROI key，默认为 "det"
//   out_rois   : string，输出 ROI key，默认为 "track"
//   feat_key   : string，ReID 特征张量 key，默认为 "tensor:reid"
//   iou_thresh : float，IoU 关联阈值，默认为 0.3
//   max_missed : int，允许丢帧次数，超过后删除轨迹，默认为 30
//   feat_alpha : float，特征 EMA 平滑系数（0–1），默认为 0.9
//   w_iou      : float，IoU 在匹配打分中的权重，默认为 0.5
//   w_reid     : float，ReID 余弦相似度权重，默认为 0.5
//   max_tracks : int，可选，GPU 轨迹容量上限，默认 256（上限 512）
class NodeTrackOcsort : public INode {
public:
    explicit NodeTrackOcsort(const std::unordered_map<std::string,std::string>& cfg);
    bool open(NodeContext& ctx) override;
    void close(NodeContext& ctx) override;
    bool process(Packet& p, NodeContext& ctx) override;
    // Graph 视图中使用 "rois:<key>" 标记 ROI 流，实际数据仍存放在 Packet.rois/gpu_rois 的 <key> 槽位中。
    std::vector<std::string> inputs() const override { return { std::string("rois:") + in_rois_key_ }; }
    std::vector<std::string> outputs() const override { return { std::string("rois:") + out_rois_key_ }; }

private:
    struct Track {
        int id {0};
        Roi box;
        std::vector<float> feat;  // L2 归一化后的平滑 ReID 向量
        bool has_feat {false};
        int missed {0};           // 连续未匹配帧数（用于删除）
        bool updated {false};     // 本帧是否被检测更新
        int age {0};              // 轨迹存活帧数（用于调试/阈值）
        int hit_streak {0};       // 连续命中次数（用于区分新轨迹与稳定轨迹）
        float vx {0.0f};          // 简单速度估计（像素/帧）
        float vy {0.0f};
        Roi last_obs;             // 最近一次观测框（用于 OCR / k_previous_obs）
        bool has_last_obs {false};
        // 近几帧观测历史：(age, bbox)，用于近似 k_previous_obs(age-delta_t,...)
        std::vector<std::pair<int,Roi>> observations;
        // CPU Kalman 状态（7 维：cx,cy,s,r, vx,vy,vs）及协方差
        float kf_x[7]  {0.0f,0.0f,0.0f,0.0f,0.0f,0.0f,0.0f};
        float kf_P[49] {0.0f};
        bool  has_kf {false};
    };

    std::string in_rois_key_ {"det"};
    std::string out_rois_key_ {"track"};
    std::string feat_key_ {"tensor:reid"};
    float iou_thresh_ {0.3f};
    int max_missed_ {30};
    float feat_alpha_ {0.9f};
    float w_iou_ {0.5f};
    float w_reid_ {0.5f};
    float det_thresh_ {0.5f};   // 检测得分阈值（高分/低分拆分）
    int   min_hits_   {3};      // 输出轨迹所需最小命中次数
    bool  use_byte_   {true};   // 是否启用 BYTE 第二阶段匹配
    int   frame_count_{0};      // 已处理帧计数
    int   delta_t_    {3};      // k_previous_obs 时间间隔
    // 深度嵌入关联权重（近似 integrated_ocsort_embedding）
    float w_assoc_emb_     {0.75f}; // 外观在关联中的权重
    float alpha_fixed_emb_ {0.95f}; // 固定嵌入 EMA 系数
    float aw_param_        {0.5f};  // 自适应权重插值参数
    bool  embedding_off_   {false}; // 关闭外观关联
    bool  aw_off_          {false}; // 关闭自适应权重，使用固定 w_assoc_emb_
    int next_id_ {1};
    int max_tracks_ {256};

    // CPU fallback 状态
    std::vector<Track> tracks_;

#if defined(USE_CUDA)
    // GPU 路径状态：仅在 VA_HAS_CUDA_KERNELS + 有有效 gpu_pool 时启用
    bool use_gpu_{false};
    bool gpu_state_ready_{false};
    va::analyzer::cudaops::OcsortGpuState gpu_state_;
    // 为 GPU 叠加构造 rois["track"] 的 GPU 视图（d_boxes/d_cls）
    va::core::GpuBufferPool* gpu_pool_{nullptr};
    va::core::GpuBufferPool::Memory gpu_boxes_mem_;
    va::core::GpuBufferPool::Memory gpu_cls_mem_;
#endif

    // CPU 实现
    bool process_cpu(Packet& p);

#if defined(USE_CUDA)
    // GPU 实现（zero-copy 轨迹 ROI）
    bool process_gpu(Packet& p, NodeContext& ctx);
#endif

    static float iou(const Roi& a, const Roi& b);
    static float cosine(const std::vector<float>& a, const float* b, int D);
    static void l2_normalize(std::vector<float>& v);
};

} } } // namespace
