# 多阶段 Analyzer 实施规划（video-analyzer）

本文档给出一个可落地、与现有代码风格兼容的“通用多阶段 Analyzer”实现规划，完全对齐《多阶段Analyzer设计.md》的思路，并结合当前仓库结构进行适配。

## 目标与范围

- 目标：在 video-analyzer 中新增一个通用、可配置的多阶段 Analyzer，支持有向无环图（DAG）或顺序执行，复用现有预处理/推理/后处理/渲染组件。
- 范围：仅新增 multistage 模块与必要的节点、图构建器及运行器，不破坏现有单阶段 Analyzer；通过配置选择启用。

## 目录与核心组件

新增目录（均在 `src/analyzer/multistage/`）：

- `interfaces.hpp`：Packet/NodeContext/INode 等通用类型
- `graph.hpp/.cpp`：节点/边/拓扑/运行
- `registry.hpp/.cpp`：节点工厂注册/创建
- `nodes_common.hpp`：通用工具与常量
- 典型节点实现：
  - `node_preproc_letterbox.hpp/.cpp`
  - `node_model.hpp/.cpp`
  - `node_nms.hpp/.cpp`
  - `node_overlay.hpp/.cpp`
- `builder_yaml.hpp/.cpp`：YAML 图解析与构建器

适配点：
- 复用 `va::core::{Frame, TensorView, HostBufferPool, GpuBufferPool}`。
- `TensorView` 无“句柄对象”，由节点内部持有 pool 的 Memory 管理生命周期，向 Packet 暴露 `data/shape/dtype` 即可。

## 通用接口与数据流

Packet/NodeContext/INode（摘要）：

- Packet
  - `frame`: `core::Frame`（支持 NV12 GPU 面或 host BGR）
  - `tensors`: `map<string, TensorView>`
  - `rois`: `map<string, vector<core::Box>>`（首版沿用 Box 作为 ROI）
  - `attrs`: `map<string, variant>`（首版可简化为 string→string）
- NodeContext
  - `cudaStream_t stream`（可为空）
  - `HostBufferPool* host_pool`, `GpuBufferPool* gpu_pool`
  - 可选：Engine/Session registry、logger 指针
- INode
  - `open/close/process`，`inputs()/outputs()`用于依赖声明与构建校验

## Graph 与运行

- Graph
  - `add_node(name, NodePtr, type, cfg)`；`add_edge(src, dst)`
  - `finalize()`: Kahn 拓扑、环检测、inputs/outputs 合规检查
  - `run(Packet&, NodeContext&)`: 按拓扑顺序执行 `process`
- Registry
  - `NodeRegistry::reg(type, factory)` / `create(type, cfg)`
  - `MS_REGISTER_NODE` 宏用于静态注册

## 最小可用节点（首批）

- 预处理：`node_preproc_letterbox`
  - 输入：`Packet.frame`（优先 NV12 GPU）
  - 输出：`tensors["tensor:det_input"]`（NCHW/F32/on_gpu）
  - 复用现有 Letterbox CUDA/CPU 逻辑；使用 `GpuBufferPool` 分配输出
- 推理：`node_model`
  - 输入：`tensors[in_key]`（默认 `tensor:det_input`）
  - 输出：`tensors["tensor:det_raw"]`（或多个输出）
  - 从 CompositionRoot/EngineRegistry 获取 `IModelSession`，调用 `run`
- 后处理（NMS）：`node_nms`
  - 输入：`tensors["tensor:det_raw"]` + letterbox meta（可通过 attrs/meta 传递）
  - 输出：`rois["det"]`（`vector<Box>`）
  - 复用 `postproc_yolo_det.cpp` 的核心逻辑（轻薄包装）
- 叠加：`node_overlay`
  - 输入：`Packet.frame` + `rois["det"]`
  - 输出：更新 `Packet.frame`（原地/拷贝），调用 `IRenderer`（CUDA/CPU）

## YAML 构建器（builder_yaml）

示例 YAML 结构（草案）：

```yaml
analyzer:
  multistage:
    nodes:
      - name: pre
        type: preproc.letterbox
        params: { out_w: 640, out_h: 640 }
      - name: det
        type: model.ort
        params: { in: tensor:det_input, outs: [tensor:det_raw], model_id: default }
      - name: nms
        type: post.yolo.nms
        params: { conf: 0.25, iou: 0.45 }
      - name: ovl
        type: overlay.cuda
        params: { alpha: 0.2, thickness: 2 }
    edges:
      - [pre, det]
      - [det, nms]
      - [nms, ovl]
```

- 解析 `nodes/edges`，通过 `NodeRegistry` 创建实例并注入参数。
- `finalize()` 进行拓扑与输入/输出键校验。

## 运行入口与集成

- 新增 `MultistageAnalyzerRunner`（实现 `IFrameFilter`）
  - 持有 `Graph/Registry/Pools/stream`，以及必要的 Engine/Renderer 引用
  - `process(in, out)`：构造 `Packet{frame=in}`，`Graph.run(pkt, ctx)`，输出 `pkt.frame` 到 `out`
- `composition_root.cpp` 集成开关：
  - 当配置启用 `multistage` 或指定 YAML 图时，构建 `MultistageAnalyzerRunner` 替代旧 `Analyzer`
  - 向 `NodeContext` 注入 `IModelSession` 工厂/缓存、`IRenderer`、Pools、stream

## 测试与样例

- 单元测试：
  - 构建 `preproc -> model(mock) -> nms -> overlay` 小图，验证 `tensors/rois/frame` 流转
  - `builder_yaml` 解析结果与手工构建等价
- 示例配置：
  - `tools/configs/analyzer_multistage_example.yaml`

## 阶段计划

1) 骨架与接口：新增 `interfaces/graph/registry`，编译通过
2) 最小节点：`preproc_letterbox/model/nms/overlay`，打通 happy-path
3) YAML 构建器：解析示例 YAML 并产出可运行图
4) 集成入口：`composition_root` 切换器与 runner 封装
5) 测试与样例：单测与示例 YAML；完善日志与报错
6) 优化与可选项：ROI 批处理、关键点节点、CUDA Graph、子图并行/stream 优化

## 关键取舍与兼容

- 类型适配：文档中的 `FrameSurface/Roi` 统一映射为现有 `core::Frame` 与 `core::Box`（首版）。
- 生命周期：`TensorView` 内仅保留指针与形状；节点内部用 buffer pool 持有内存，避免悬挂指针。
- 性能策略：首版按拓扑顺序执行；后续可引入 CUDA Graph、tile/binning、并行子图等优化。
- 可观测性：Graph/Node 增加日志前缀与失败早停，便于运维排障。

---

如需，我可以基于本规划直接提交骨架代码与最小节点的初版实现，以及对应的 YAML 样例与单测用例。
