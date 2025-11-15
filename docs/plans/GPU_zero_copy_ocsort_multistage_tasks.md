# GPU 零拷贝 OCSORT 多阶段追踪实施任务清单（WBS）

本文档基于 `docs/references/GPU_zero_copy_ocsort_multistage_plan.md` 的设计方案，拆解在 VA 中实现“检测 + ReID + 追踪 + 叠加全 GPU 零拷贝”的任务列表，强调渐进演进和对现有功能的兼容性。

---

## 阶段 1：基础结构改造（保持现有行为不变）

### 1.1 Packet 扩展

- [ ] 在 `video-analyzer/src/analyzer/multistage/interfaces.hpp` 中：
  - [ ] 定义 `GpuRoiBuffer` 结构，用于在 GPU 上表达 ROI：
    - `float* d_boxes;`  // [N,4]
    - `float* d_scores;` // [N]
    - `int32_t* d_cls;`  // [N]
    - `int32_t count;`
  - [ ] 在 `Packet` 中新增：
    - `std::unordered_map<std::string, GpuRoiBuffer> gpu_rois;`
- [ ] 确认所有现有节点在未使用 `gpu_rois` 时行为不变（编译通过且逻辑不依赖新字段）。

### 1.2 NodeNmsYolo 增强：输出 GPU ROI

- [ ] 在 `NodeNmsYolo` 构造函数中解析可选参数：
  - [ ] `emit_gpu_rois`（默认 0），支持 `"1"/"true"/"on"` 作为开启值。
- [ ] 在 CUDA NMS 路径（使用 `YoloDetectionPostprocessorCUDA`）中：
  - [ ] 从现有 CUDA NMS 实现中获取抑制后的 GPU boxes/scores/classes；
  - [ ] 当 `emit_gpu_rois=1` 时，构造 `GpuRoiBuffer` 并写入 `p.gpu_rois["det"]`；
  - [ ] 始终保留原有从 `ModelOutput` 填充 `p.rois["det"]` 的逻辑。
- [ ] 验证：不配置 `emit_gpu_rois` 的检测 Graph 行为完全一致（输出结果与性能无差异）。

---

## 阶段 2：GPU OCSORT + EMA 内核开发

### 2.1 新增 CUDA 模块 track_ocsort_kernels

- [ ] 在 `video-analyzer/src/analyzer/cuda/` 下新增文件：
  - [ ] `track_ocsort_kernels.hpp`
  - [ ] `track_ocsort_kernels.cu`
- [ ] 在头文件中定义 GPU 轨迹状态：

```cpp
struct OcsortGpuState {
    float*   d_track_boxes;    // [T_max,4]
    float*   d_track_feats;    // [T_max,D]
    int32_t* d_track_ids;      // [T_max]
    int32_t* d_track_missed;   // [T_max]
    uint8_t* d_track_has_feat; // [T_max]
    int32_t* d_track_count;    // 单元素 device int
    int32_t  max_tracks;
    int32_t  feat_dim;
};
```

- [ ] 在 `.cu` 中实现核心内核：
  - [ ] IoU 计算 kernel：与现有 NMS 内核使用一致的坐标与 IoU 定义；
  - [ ] ReID 余弦相似度 kernel：轨迹特征视为单位向量，对检测特征按需归一；
  - [ ] 匹配得分计算：`score = w_iou * IoU + w_reid * cosine`，IoU 低于阈值直接记为 0；
  - [ ] 基于 score 的贪心匹配：
    - 展平 `(t,d,score)` 为一维数组；
    - 使用 Thrust 在 GPU 上按 score 降序排序；
    - 在 kernel 中利用 `track_used[t]` / `det_used[d]` 标记数组执行贪心匹配；
  - [ ] 轨迹更新：
    - 匹配轨迹：更新 box、EMA 平滑特征、L2 归一、`missed=0`；
    - 新建轨迹：为未匹配检测分配新 slot 和新 `track_id`，初始化 box/feat；
  - [ ] 轨迹清理与压缩：对 `missed > max_missed` 的轨迹标记并使用前缀和/prefix-sum 压缩数组，更新 `d_track_count`。

### 2.2 导出统一入口

- [ ] 在 `track_ocsort_kernels.hpp` 中声明：

```cpp
cudaError_t ocsort_match_and_update(
    const GpuRoiBuffer& det_rois,
    const float* d_det_feats,     // [N,D] 或 nullptr
    OcsortGpuState& state,
    float iou_thresh,
    float feat_alpha,
    float w_iou,
    float w_reid,
    int   max_missed,
    int   next_id_base,
    cudaStream_t stream);
```

- [ ] 确保入口函数对 `d_det_feats=nullptr` 情况退化为纯 IoU OCSORT。

### 2.3 CMake 集成

- [ ] 在 `video-analyzer/CMakeLists.txt` 中：
  - [ ] 将 `src/analyzer/cuda/track_ocsort_kernels.cu` 纳入 `CUDA_SOURCES`（受 `HAVE_CUDA_KERNELS` 控制）；
  - [ ] 确保 NVCC 配置与现有 CUDA 内核（NMS、overlay、preproc）一致。
- [ ] 在 Docker GPU 构建环境中验证编译通过。

---

## 阶段 3：NodeTrackOcsort GPU-only 改造

### 3.1 节点配置与状态初始化

- [ ] 在 `NodeTrackOcsort` 构造函数中解析 YAML 参数：
  - [ ] `in_rois`（默认 `"det"`）、`out_rois`（默认 `"track"`）；
  - [ ] `feat_key`（默认 `"tensor:reid"`）；
  - [ ] `iou_thresh`、`max_missed`；
  - [ ] `feat_alpha`、`w_iou`、`w_reid`；
  - [ ] 可选：`max_tracks`、`feat_dim`。
- [ ] 在 `open(NodeContext&)` 中：
  - [ ] 检查 `USE_CUDA` 与 `ctx.gpu_pool` / `ctx.stream` 是否可用；
  - [ ] 根据 `max_tracks` 与 `feat_dim` 分配并初始化 `OcsortGpuState` 对应的 device 缓冲；
  - [ ] 定义无 GPU 时的策略：
    - OCSORT 专用 Graph：可直接报错拒绝加载（强制全 GPU）；或
    - 允许 fallback 到 CPU 实现（兼容模式）。

### 3.2 process() 中的 GPU 路径

- [ ] 在 `process(Packet& p, NodeContext& ctx)` 中：
  - [ ] 从 `p.gpu_rois[in_rois_key_]` 读取 NMS 之后的检测 boxes/scores/cls；
  - [ ] 从 `p.tensors[feat_key_]` 读取 ReID 特征：
    - 要求 `on_gpu=true`、`dtype = F32`、`shape = [N,D]`；
    - 不满足时，按策略退化为纯 IoU 匹配或报错。
  - [ ] 调用 `ocsort_match_and_update(...)` 完成匹配、轨迹状态更新与轨迹压缩；
  - [ ] 构造 `GpuRoiBuffer track_rois`：
    - `d_boxes` 指向当前有效轨迹的 boxes；
    - `d_cls` 指向对应的 `track_ids`（复用 cls 字段展示 id）；
    - `count` 使用 `d_track_count`；
  - [ ] 写入 `p.gpu_rois[out_rois_key_] = track_rois`；
  - [ ] 在“全 GPU 零拷贝”模式下，不再填充 `p.rois[out_rois_key_]`。
- [ ] 保留清晰的 CPU fallback（如有需要），但在 OCSORT 专用 Graph 中推荐配置为“无 GPU 直接报错”以保证零拷贝假设成立。

---

## 阶段 4：Overlay 支持 GPU ROI 渲染

### 4.1 OverlayRendererCUDA 增强

- [ ] 在 `video-analyzer/src/analyzer/renderer_overlay_cuda.hpp/.cpp` 中：
  - [ ] 增加接口 `bool draw_gpu_rois(const core::Frame& in, const GpuRoiBuffer& rois, core::Frame& out, cudaStream_t stream);`
  - [ ] 内部调用 CUDA kernel 从 `GpuRoiBuffer` 的 boxes/cls 在 GPU 上直接画框与标签；
  - [ ] 与现有 overlay 样式（颜色、厚度、字体大小）保持一致。

### 4.2 NodeOverlay 增强（选择性使用 GPU ROI）

- [ ] 在 `NodeOverlay` 构造中解析新参数：
  - [ ] `use_gpu_rois`（默认 0）；
- [ ] 在 `NodeOverlay::process(Packet& p, NodeContext& ctx)` 中：
  - [ ] 若 `use_gpu_rois==1` 且 renderer 为 CUDA 且存在 `p.gpu_rois[rois_key_]`：
    - [ ] 调用 `draw_gpu_rois(...)`，仅使用 GPU ROI 视图；
  - [ ] 否则：
    - [ ] 保持现有 CPU ROI → `ModelOutput` → `draw(...)` 流程不变。

---

## 阶段 5：OCSORT 专用 Graph 与配置

### 5.1 analyzer_multistage_ocsort 图更新

- [ ] 在 `docker/config/va/graphs/analyzer_multistage_ocsort.yaml` 中：
  - [ ] 为 `nms` 节点添加 `emit_gpu_rois: "1"`；
  - [ ] 确保 `roi.batch.cuda` 与 `reid` 模型输出在 GPU（ReID 模型使用 CUDA Provider）；
  - [ ] 为 `track.ocsort` 配置：
    - `in_rois: "det"`、`out_rois: "track"`；
    - `feat_key: "tensor:reid"`；
    - `iou_thresh`、`max_missed`、`feat_alpha`、`w_iou`、`w_reid`；
  - [ ] 为 `overlay.cuda` 配置：

```yaml
- name: ovl
  type: overlay.cuda
  params:
    rois: "track"
    alpha: "0.2"
    thickness: "3"
    use_gpu_rois: "1"
```

- [ ] 保证其他纯检测 Graph 不配置 `emit_gpu_rois` / `use_gpu_rois`，行为完全不变。

### 5.2 Engine/ORT 配置校验

- [ ] 针对 OCSORT 图使用的 ReID 模型：
  - [ ] 确认 ORT/TensorRT Provider 使用 CUDA，输出 tensor 在 GPU；
  - [ ] 若引擎支持 host staging（如 `stage_device_outputs`），在该图配置中关闭，避免多余 D2H 拷贝。

---

## 阶段 6：验证与回归

### 6.1 功能验证

- [ ] 在 GPU Docker 环境中重建 VA GPU 镜像；
- [ ] 使用 `analyzer_multistage_ocsort` 图进行端到端测试：
  - [ ] 验证检测框与原有 NMS 结果一致（cap/日志比对）；
  - [ ] 验证 OCSORT 轨迹 ID 稳定性（遮挡、短期丢失、交叉等场景）；
  - [ ] 验证 ReID 参与后的匹配效果与仅 IoU 版本差异是否符合预期。

### 6.2 性能与零拷贝验证

- [ ] 使用日志/指标或 profiler 检查：
  - [ ] 检测 → NMS → ROI → ReID → track → overlay 链路是否避免大规模 CPU↔GPU 拷贝；
  - [ ] CPU 侧仅在调试/回退路径才访问 ROI/特征。
- [ ] 对比 CPU OCSORT 实现与 GPU 版本在延迟、吞吐上的差异。

### 6.3 回归确认

- [ ] 在仅使用纯检测 Graph 的配置下启动 VA：
  - [ ] 确认 HTTP/gRPC/前端展示结果与改动前一致；
  - [ ] 确认性能无明显退化；
  - [ ] 确认日志中无与 GPU ROI/OCSORT 相关的异常告警。

---

## 附：实施策略建议

- 优先完成阶段 1（Packet + NodeNmsYolo 增强），单独提交以方便代码审查；
- 阶段 2–3 可以在一个 GPU feature 分支中迭代开发，期间保持 CPU fallback 可用；
- 阶段 4–5 落地后，在小范围环境中验证 OCSORT GPU 方案，收集指标与反馈；
- 阶段 6 完成后，将 OCSORT GPU 图作为推荐配置加入文档，并保留 CPU 版本作为降级方案。

