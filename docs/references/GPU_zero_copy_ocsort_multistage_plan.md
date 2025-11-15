# GPU 零拷贝 OCSORT 多阶段追踪方案（规划稿）

本文档梳理在 Video Analyzer（VA）中，将“检测 + ReID + 目标追踪 + 叠加”全部迁移到 GPU 上、实现 ROI 与轨迹元数据零拷贝的整体方案。目标是在不影响现有目标检测功能的前提下，为 OCSORT 场景提供一条专用的、全 GPU 多阶段链路。

---

## 1 目标与约束

- 业务目标：
  - 在 VA 多阶段 Graph 中，以 `pre → det → nms → roi → reid → track → ovl` 的形式表达完整的目标追踪流水线；
  - 检测、NMS、ReID 推理、OCSORT 匹配与 EMA、叠加渲染均在 GPU 上完成，以最小化 CPU 参与和显存拷贝。
- 约束：
  - 不修改现有目标检测图的行为（默认路径仍使用 CPU `rois` 与现有 overlay 实现）；
  - 新增/增强能力通过 YAML 参数显式开启，仅在 OCSORT 专用图中生效；
  - 与现有 CUDA NMS / CUDA overlay 内核保持一致风格，复用既有基础设施（`GpuBufferPool`、`NodeContext::stream` 等）。

---

## 2 Packet 扩展：加入 GPU ROI 视图

现有 `multistage::Packet` 仅通过 `rois: std::unordered_map<std::string, std::vector<Roi>>` 以 CPU 形式表达 ROI。为支持全 GPU 流水线，需要为 ROI 增加 GPU 视图：

- 新增结构 `GpuRoiBuffer`：
  - `float* d_boxes`：`[N,4]`，`(x1,y1,x2,y2)`；
  - `float* d_scores`：`[N]`，可选（用于后续按置信度渲染或调试）；
  - `int32_t* d_cls`：`[N]`，可选（在检测阶段表示类别，在追踪阶段复用为 `track_id`）；
  - `int32_t count`：有效 ROI 数量 `N`。
- 在 `Packet` 中新增：
  - `std::unordered_map<std::string, GpuRoiBuffer> gpu_rois;`

约定：

- `rois[...]`（CPU）继续用于现有检测/叠加/调试路径；
- `gpu_rois[...]`（GPU）用于新引入的全 GPU 零拷贝链路，例如 `gpu_rois["det"]`、`gpu_rois["track"]`。

---

## 3 NodeNmsYolo 增强：输出 GPU ROI（兼容）

### 3.1 设计原则

- 不新增新的 NMS 节点类型，仅增强现有 `NodeNmsYolo`；
- 保持当前行为不变：
  - 始终通过 `YoloDetectionPostprocessor` / `YoloDetectionPostprocessorCUDA` 生成 `ModelOutput`；
  - 始终写入 `p.rois["det"]`，保证 CPU 端目标检测功能与现有实现完全一致；
- 在 CUDA NMS 路径下，*可选* 地追加 `gpu_rois["det"]` 视图，供 GPU 追踪使用。

### 3.2 配置参数

在 `NodeNmsYolo` 构造函数中新增可选参数：

- `emit_gpu_rois`（默认：`0`）：
  - `"1"/"true"/"on"`：在 CUDA NMS 路径下，输出 `gpu_rois[in_key]`；
  - 其他/未配置：仅输出 CPU `rois[...]`，行为与当前版本一致。

### 3.3 实现要点

- 在 CUDA NMS 分支（`YoloDetectionPostprocessorCUDA`）中，已有：
  - GPU 端紧凑的 boxes / scores / classes 输出；
  - NMS 逻辑（IoU、排序、bitmask 抑制）已经由 `postproc_yolo_nms_kernels.cu` 实现。
- 若 `emit_gpu_rois` 为真且 NMS 走的是 CUDA 路径：
  - 构造 `GpuRoiBuffer det_gpu`：
    - `d_boxes` 指向 NMS 后的 `[N_keep,4]` GPU 缓冲；
    - `d_scores` / `d_cls` 指向对应 GPU 缓冲（如有）；
    - `count = N_keep`；
  - 写入 `p.gpu_rois["det"] = det_gpu`。
- CPU 端 `p.rois["det"]` 始终从 `ModelOutput` 填充，保证 HTTP/gRPC 和 CPU overlay 行为不变。

### 3.4 Graph 使用示例

- 现有检测图（不改 YAML）：
  - `emit_gpu_rois` 不配置 → 不产生 `gpu_rois`，行为与当前完全一致。
- OCSORT 图启用 GPU ROI 输出：

```yaml
- name: nms
  type: post.yolo.nms
  params:
    conf: "0.30"
    iou: "0.70"
    use_cuda: "1"
    emit_gpu_rois: "1"
```

---

## 4 全 GPU OCSORT + EMA：track_ocsort_kernels

为实现“匹配 + EMA 完全在 GPU 上”，需要在 `analyzer/cuda` 下新增一套 OCSORT CUDA 内核：

- 新文件：
  - `src/analyzer/cuda/track_ocsort_kernels.hpp`
  - `src/analyzer/cuda/track_ocsort_kernels.cu`

### 4.1 GPU 轨迹状态

定义 GPU 侧持久化的轨迹状态结构：

```cpp
struct OcsortGpuState {
    float*   d_track_boxes;    // [T_max,4] 轨迹框 (x1,y1,x2,y2)
    float*   d_track_feats;    // [T_max,D] L2 归一后的轨迹 ReID 特征
    int32_t* d_track_ids;      // [T_max]   轨迹 ID
    int32_t* d_track_missed;   // [T_max]   未匹配帧计数
    uint8_t* d_track_has_feat; // [T_max]   是否已有有效特征
    int32_t* d_track_count;    // 设备端当前轨迹数 T（单元素）
    int32_t  max_tracks;       // 轨迹上限
    int32_t  feat_dim;         // 特征维度 D
};
```

- 在 `NodeTrackOcsort::open()` 内根据配置（`max_tracks`、`feat_dim`）分配对应 device 缓冲；
- Graph 生命周期内常驻 GPU，跨帧复用。

### 4.2 GPU OCSORT 入口

导出的主函数接口示意：

```cpp
cudaError_t ocsort_match_and_update(
    const GpuRoiBuffer& det_rois, // NMS 输出：GPU boxes/scores/cls
    const float* d_det_feats,     // [N,D] ReID 特征 (GPU tensor)，可为 nullptr
    OcsortGpuState& state,        // 持久化轨迹状态
    float iou_thresh,
    float feat_alpha,
    float w_iou,
    float w_reid,
    int   max_missed,
    int   next_id_base,
    cudaStream_t stream);
```

职责：

1. 从当前轨迹 (`state`) 与本帧检测 (`det_rois`、`d_det_feats`) 构造 `(T,N)` 匹配得分：
   - IoU：与 CUDA NMS 相同的定义；
   - ReID 余弦相似度：轨迹特征假定为单位向量，检测特征在 kernel 中按需归一；
   - 得分：`score = w_iou * IoU + w_reid * cosine`，IoU 低于阈值直接视为不可匹配。
2. 在 GPU 上执行贪心匹配：
   - 将 `(t,d,score)` 展平为一维数组；
   - 使用 Thrust 在 GPU 上按 `score` 降序排序；
   - 在 kernel 内使用 `track_used[t]` / `det_used[d]` 标记数组完成贪心匹配。
3. 更新轨迹状态：
   - 匹配到的 `(t,d)`：
     - 更新 `d_track_boxes[t]`；
     - 若存在特征，则按 `feat_alpha` 对 `d_track_feats[t]` 与 `d_det_feats[d]` 做 EMA，再 L2 归一；`has_feat[t]=1`；
     - `missed[t]=0`。
   - 未匹配的检测 `d`：
     - 若 `track_count < max_tracks`，创建新轨迹：
       - `id = next_id_base + offset`；
       - 初始化 `box` + `feat`（如有）。
   - 未更新的轨迹：
     - `missed[t]++`，超出 `max_missed` 的在后续 compact kernel 中删除。
4. 构造当前帧的轨迹 ROI 视图：
   - 形成 `GpuRoiBuffer track_rois`（指向当前有效轨迹的 boxes / ids），供 overlay 直接使用。

整个过程不将轨迹或特征拷回 CPU，仅在需要调试或 CPU overlay 时再显式 D2H。

---

## 5 NodeTrackOcsort 改造：GPU-only 追踪节点

`NodeTrackOcsort` 在当前版本中已经实现了 CPU 版 IoU+ReID+EMA 逻辑。为支持纯 GPU 模式，需要：

### 5.1 配置参数（YAML）

在节点参数中支持：

- `in_rois`：输入 ROI key，默认 `"det"`；
- `out_rois`：输出 ROI key，默认 `"track"`；
- `feat_key`：ReID 特征 tensor key，默认 `"tensor:reid"`；
- `iou_thresh`：IoU 阈值，默认 `0.3`；
- `max_missed`：最大丢帧次数，默认 `30`；
- `feat_alpha`：特征 EMA 系数，默认 `0.9`；
- `w_iou` / `w_reid`：IoU / ReID 在匹配得分中的权重，默认各 `0.5`。

### 5.2 生命周期

- `open()`：
  - 检查 `USE_CUDA` + `NodeContext::gpu_pool/stream` 是否可用；
  - 根据最大轨迹数、ReID 维度初始化并分配 `OcsortGpuState`；
  - 若 GPU 不可用，可选择：
    - 直接报错并拒绝加载该 Graph（用于“强制全 GPU”场景）；或
    - 回退到现有 CPU 实现（用于“兼容但尽量用 GPU”场景）。
- `process()`（GPU 路径）：
  - 从 `p.gpu_rois[in_rois_key_]` 取 NMS 之后的检测 ROI（boxes/scores/cls）。
  - 从 `p.tensors[feat_key_]` 获取 ReID 特征：
    - 要求 `on_gpu=true`，`dtype=F32`，`shape=[N,D]`；
    - 若不满足，可选择视为“无特征，仅 IoU OCSORT”，或直接报错。
  - 调用 `ocsort_match_and_update(...)` 完成匹配与轨迹更新；
  - 构造 `p.gpu_rois[out_rois_key_]` 指向更新后的轨迹 boxes/ids（GPU）；
  - 在“全 GPU”模式下，不再填充 `p.rois[...]`，避免引入 CPU 拷贝。
- `close()`：
  - 释放 `OcsortGpuState` 对应的 device 缓冲。

---

## 6 Overlay 增强：支持 GPU ROI 渲染（不改默认行为）

### 6.1 OverlayRendererCUDA 新接口

在 `OverlayRendererCUDA` 中新增：

- `bool draw_gpu_rois(const core::Frame& in, const GpuRoiBuffer& rois, core::Frame& out, cudaStream_t stream);`

职责：

- 从 `GpuRoiBuffer` 的 `d_boxes / d_cls` 直接在 `in` 的 GPU 像素上画框和标签；
- 不需要任何 CPU ROI 或 `ModelOutput::boxes`；
- 与现有 CUDA overlay kernel（颜色、厚度、字体等）保持一致。

### 6.2 NodeOverlay 参数增强

在 `NodeOverlay` 中新增可选参数：

- `use_gpu_rois`（默认 `0`）：
  - `"1"/"true"/"on"`：在 CUDA overlay 路径下优先使用 `p.gpu_rois[rois_key]`；
  - 其他/未配置：保持现有行为，仅使用 `p.rois[...]`。

`process()` 逻辑：

- 若 `use_gpu_rois==1` 且存在 `p.gpu_rois[rois_key_]` 且 renderer 为 CUDA：
  - 调用 `draw_gpu_rois`，完全在 GPU 上完成叠加；
- 否则：
  - 走现有 CPU ROI → `ModelOutput` → `draw(...)` 路径，兼容所有旧图。

---

## 7 OCSORT 专用 Graph 配置建议

在 `docker/config/va/graphs/analyzer_multistage_ocsort.yaml` 中，推荐的“全 GPU 零拷贝追踪”配置：

- NMS：

```yaml
- name: nms
  type: post.yolo.nms
  params:
    conf: "0.30"
    iou: "0.70"
    use_cuda: "1"
    emit_gpu_rois: "1"
```

- ROI + ReID：

```yaml
- name: roi
  type: roi.batch.cuda
  params:
    in_rois: "det"
    out: "tensor:roi_batch"
    out_w: "128"
    out_h: "256"
    max_rois: "128"

- name: reid
  type: model
  params:
    in: "tensor:roi_batch"
    outs: "tensor:reid"
    model_path_ort: "models/reid_x.onnx"
    model_path: "models/reid_x.onnx"
```

- OCSORT 追踪：

```yaml
- name: track
  type: track.ocsort
  params:
    in_rois: "det"
    out_rois: "track"
    feat_key: "tensor:reid"
    iou_thresh: "0.30"
    max_missed: "30"
    feat_alpha: "0.90"
    w_iou: "0.5"
    w_reid: "0.5"
```

- 叠加渲染：

```yaml
- name: ovl
  type: overlay.cuda
  params:
    rois: "track"
    alpha: "0.2"
    thickness: "3"
    use_gpu_rois: "1"
```

现有纯检测 Graph 不配置 `emit_gpu_rois` / `use_gpu_rois`，行为完全不变。

---

## 8 对现有功能的影响

- NodeNmsYolo / NodeOverlay 默认行为不变：
  - 不配置新参数时，只走 CPU `rois[...]` 与当前逻辑；
  - 现有检测图、HTTP/gRPC 输出、日志都保持一致；
- 新的 GPU 零拷贝路径仅在：
  - Graph 显式开启 `emit_gpu_rois` 与 `use_gpu_rois`；
  - `track.ocsort` 节点存在且 GPU 可用；
  时才启用。

通过该方案，可以在 OCSORT 场景下实现“检测 + ReID + 追踪 + 叠加”全在 GPU 上完成的多阶段流水线，同时不影响已有目标检测功能与接口行为。

