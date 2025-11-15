# Video Analyzer 详细设计说明书（2025-11-14）

## 1 概述

### 1.1 目标

本说明书描述 `video-analyzer/` 子项目的详细设计，包括模块划分、关键数据结构、核心流程与非功能性设计，以支撑后续维护、优化与新特性的扩展。

### 1.2 范围

- 仅覆盖 Video Analyzer 进程本身（C++ 后端分析引擎），不包括 Controlplane、VSM、前端等其他子系统。
- 控制平面 gRPC 接口、训练流水线等在相关设计文档中单独说明，此处仅涉及 VA 侧对这些接口的实现部分。

### 1.3 相关文档

- 概要设计：`docs/design/architecture/整体架构设计.md`
- 控制平面设计：`docs/design/architecture/controlplane_design.md`
- LRO 订阅设计：`docs/design/subscription_lro/lro_subscription_design.md`
- WebRTC / WHEP 协议：`docs/design/protocol/webrtc-protocol.md`
- 存储访问详细设计：`docs/design/storage/storage_详细设计.md`
- 日志与指标：`docs/design/observability/LOGGING.md`、`docs/design/observability/METRICS.md`

## 2 模块划分

VA 源码主要分布在 `video-analyzer/src/` 目录，按职责划分为以下模块：

- `app/`：应用层，提供 `va::app::Application`，负责组合配置、EngineManager、PipelineBuilder、TrackManager 与 REST/metrics 服务。
- `core/`：核心基础设施：
  - `EngineManager`：执行引擎管理（provider、设备号、IoBinding/TensorRT/Triton 等）。
  - `PipelineBuilder`：根据 Profile/模型/参数构建多阶段 Graph 与 Pipeline。
  - `TrackManager`：管理每路流的 Pipeline 生命周期与统计信息。
  - 工厂与通用配置结构（SourceConfig/EncoderConfig/TransportConfig 等）。
- `analyzer/`：分析链路：
  - 预处理、后处理、YOLO/NMS/ReID 等算子实现。
  - CUDA/CPU 双路径的 kernel 与包装。
- `media/`：媒体与传输：
  - RTSP 拉流与解码（NVDEC/FFmpeg）。
  - H.264 编码（NVENC/FFmpeg）。
  - WebRTC DataChannel 传输与 WHEP 会话管理。
- `server/`：对外接口层：
  - HTTP REST 服务（`RestServer`）与路由（`rest_routes.cpp`）。
  - 观察性接口（日志、指标、sessions、admin WAL 等）。
  - WHEP HTTP 接口与 gRPC 控制平面（`control_plane_embedded`）。
- `storage/`：数据库访问抽象：
  - `DbPool` 与多个 `Repo`（Session/Event/Log/Source/Graph）。
  - 用于记录会话、日志与事件等控制面数据。
- `controlplane/`：内嵌控制平面适配层：
  - gRPC `AnalyzerControl` 服务实现，连接 VA 内部引擎与外部 Controlplane。

顶层的 `composition_root.cpp` 负责根据配置实例化上述模块并完成依赖装配。

## 3 关键类与数据结构

### 3.1 Application 层（`va::app::Application`）

`Application` 是 VA 进程的组合根，外部通常仅与该类交互：

- 生命周期管理：
  - `bool initialize(const std::string& config_dir)`：加载配置、初始化 EngineManager、PipelineBuilder、TrackManager、RestServer 等。
  - `bool start()` / `void shutdown()`：启动/停止 HTTP 服务、监控线程等。
- 控制接口：
  - 订阅管理：`subscribeStream/ unsubscribeStream/ switchSource/ switchModel/ switchTask/ updateParams`。
  - 引擎管理：`setEngine / engineRuntimeStatus / currentEngine`。
  - 状态查询：`pipelines()`（列出当前 pipeline 信息）、`systemStats()`（聚合统计）、`ffmpegEnabled()`。
- 配置展开：
  - `buildSourceConfig/buildFilterConfig/buildEncoderConfig/buildTransportConfig`：从 Profile/模型/参数拼装 `core` 层配置，供 PipelineBuilder 使用。
- 控制平面内嵌（在开启 gRPC 时）：
  - `applyPipeline/applyPipelines/removePipeline/drainPipeline/getPipelineStatus`：封装 pipeline 级编排。
  - `pipelineController`：返回控制平面执行器，用于 CP gRPC 服务。

### 3.2 核心数据结构（核心模块）

- `va::core::SourceConfig`：
  - 描述 RTSP 源以及解码策略（URL、解码方式、缓冲策略等）。
- `va::core::FilterConfig`：
  - 描述分析链路参数（graph id、任务/模型 id、分析参数、预处理/后处理配置等）。
- `va::core::EncoderConfig`：
  - 编码参数（分辨率、帧率、码率、编码器类型、GOP、NVENC 码控策略等）。
- `va::core::TransportConfig`：
  - 媒体传输配置（WebRTC/WHEP 端点、DataChannel 配置、重连策略等）。
- `va::core::EngineDescriptor`：
  - 执行引擎选择（provider：cpu/cuda/tensorrt/triton、device、options map）。
- `va::core::EngineRuntimeStatus`：
  - 当前引擎运行态（provider、gpu_active、io_binding/device_binding、cpu_fallback 等）。

这些配置由 `Application` 基于 `config/*.yaml` 展开，并传给 `PipelineBuilder` 构建实际的多阶段 Graph 与 Pipeline 实例。

### 3.3 订阅与 LRO 相关结构

订阅作为长耗时操作由 LRO Runner 承载（详细见 `lro_subscription_design.md`），在 VA 内部主要涉及：

- Operation：
  - `id`、`spec_json`（订阅请求的 JSON 规格）、`status`（Phase + 状态）、`timeline`（各阶段时间戳）、`result_json`（包含 `pipeline_key` 等）。
- Step：
  - 逻辑阶段：`preparing` / `opening_rtsp` / `loading_model` / `starting_pipeline`。
  - 每个 Step 对应具体实现：
    - `preparing`：校验参数与配置，准备 SourceConfig/FilterConfig 等。
    - `opening_rtsp`：打开 RTSP 源，探测 caps，写入错误原因 `open_rtsp_*`。
    - `loading_model`：加载/预热模型，写入 `load_model_*` 类错误。
    - `starting_pipeline`：构建并启动 Pipeline，将 `pipeline_key` 写入 result。
- AdmissionPolicy：
  - 多桶信号量：`open_rtsp/load_model/start_pipeline` 限制各阶段并发度。
  - 支持队列上限与 `Retry-After` 估算（由外层 REST/CP 映射为 HTTP 行为）。

## 4 核心流程

### 4.1 配置加载与启动流程

1. 进程入口 `main.cpp` 创建 `va::app::Application` 实例。
2. 调用 `initialize(config_dir)`：
   - 使用 `ConfigLoader` 解析 `app.yaml`、`models.yaml`、`profiles.yaml`、`analyzer_params.yaml`。
   - 初始化 `EngineManager` 并按配置设置默认 provider（CPU/CUDA/TensorRT/Triton）。
   - 实例化 `PipelineBuilder`、`TrackManager`。
   - 依据 `app.yaml` 初始化 REST 服务器与 metrics 服务器。
3. 调用 `start()`：
   - 启动 HTTP 监听端口（通常 `:8082`），注册所有 REST route（详见 `rest_routes.cpp`）。
   - 若启用 gRPC，启动控制平面 gRPC 服务（`AnalyzerControl`）。

### 4.2 订阅创建流程（VA 内部视角）

当 Controlplane 或旧 REST `/api/subscribe` 请求订阅时，VA 内部主要执行：

1. 参数归一化：
   - 针对兼容字段（`stream/stream_id`、`profile`、`url/source_uri` 等）统一解析。
   - 决定模型选择（Profile 默认模型 vs 显式 `model_id`），解析分析参数。
2. LRO Operation 创建：
   - 构造 `spec_json`，包括流标识、Profile 名、源 URI、模型 ID 等。
   - 将 Operation 投入 LRO Runner 队列，等待调度执行。
3. 阶段执行：
   - `preparing`：校验配置与环境（GPU/模型文件等）。
   - `opening_rtsp`：构建 `SourceConfig` 并尝试打开 RTSP 源，发生错误时写入标准化 reason。
   - `loading_model`：根据 EngineDescriptor 加载/预热模型（ONNX/TensorRT/Triton），并更新 Engine runtime 信息。
   - `starting_pipeline`：调用 `Application::subscribeStream`：
     - 通过 `PipelineBuilder` 构建 Pipeline，并注册到 `TrackManager`。
     - 启动 Pipeline，将 `pipeline_key` 返回给调用方。
   - 成功后将 Operation 标记为 `Ready` 并写入 `result_json`。
4. 状态与指标：
   - 各阶段的耗时、失败原因和队列长度通过 LRO metrics 导出为 Prometheus 指标。
   - 控制平面通过 gRPC 或 HTTP `/api/system/info` 获取摘要信息。

### 4.3 Pipeline 运行流程

对于每一路订阅成功的 Pipeline，运行流程如下：

1. 源节点从 RTSP 拉流（NVDEC/FFmpeg），得到 NV12 或 BGR 帧。
2. 预处理节点按 Profile 配置对帧进行缩放、归一化与 letterbox，生成 NCHW tensor：
   - 优先 CUDA 预处理（零拷贝路径），必要时回退到 CPU + OpenCV。
3. 模型节点通过 `IModelSession` 调用 ONNX Runtime/TensorRT/Triton 完成推理：
   - 支持 IoBinding 与 GPU/CPU 输出的不同组合；
   - 支持 TensorRT plan 和 Triton gRPC/In-Process 模式。
4. 后处理节点对模型输出执行 YOLO decode/NMS、ReID 等操作：
   - GPU NMS 与 CPU NMS 向行为对齐，细节见 `lro_subscription_design.md` 与相关后处理设计文档。
5. 叠加节点在 GPU/CPU 上绘制检测框/遮罩。
6. 编码节点将叠加后帧编码为 H.264（NVENC/FFmpeg）或 JPEG。
7. 传输节点将编码后数据推送给 WHEP 会话或 WebRTC DataChannel：
   - 当前推荐仅启用 WHEP，DataChannel 作为兼容/调试路径。
8. Pipeline 运行期间，`TrackManager` 定期采样 FPS、延迟与掉帧统计，并更新指标。

### 4.4 取消与回收流程

当外部请求取消订阅或 Pipeline 超时/空闲时：

1. LRO Operation 标记为 `Cancelled`，必要时执行回调释放资源。
2. `TrackManager` 调用 Pipeline 的停止逻辑，关闭源、释放模型与编码器句柄。
3. 取消操作与完成状态写入数据库（如已启用 DB），供后续审计与查询。

## 5 接口与交互

### 5.1 gRPC 接口（控制平面）

当启用 gRPC 控制平面时，VA 暴露 `AnalyzerControl` 服务，主要方法包括：

- `Subscribe/Cancel/Get/Watch`：
  - 封装订阅 LRO 操作与 Pipeline 状态查询。
  - 由 Controlplane 转译为 `/api/subscriptions` HTTP API。
- `QueryRuntime`：
  - 返回 Engine runtime 信息，作为 CP `/api/va/runtime` 的数据来源。

## 6 非功能性设计

### 6.1 性能与扩展性

- 零拷贝主路径：通过 NVDEC + CUDA 预处理 + TensorRT/Triton In-Process + GPU overlay + NVENC 实现端到端 GPU pipeline。
- IOBinding 与共享缓冲：在 ONNX Runtime/TensorRT/Triton 中尽可能复用缓冲区，减少 host/device 之间的拷贝。
- 多阶段 Graph 与节点拆分：通过多阶段节点（预处理/推理/后处理/叠加）实现灵活组合与按需扩展。

### 6.2 可观测性

- 日志：
  - 统一通过 `observability` 段配置输出（级别/格式/模块），支持运行时更新。
  - 关键路径（订阅、模型加载、NMS、编码与传输）均按模块打点。
- 指标：
  - 通过 `/metrics` 暴露 Prometheus 指标，涵盖 Pipeline FPS、延迟、掉帧、编码器统计与订阅 LRO 指标等。
  - 路径标签与扩展标签的定义见 `METRICS.md` 与 `metrics_path_labels.md`。

### 6.3 健壮性与回退

- 执行引擎回退链：Triton > TensorRT > CUDA (ORT) > CPU (ORT)，在上游依赖不可用时自动降级。
- 解码与编码回退：NVDEC/NVENC 出现故障时可回退到 CPU 解码/编码（代价是性能下降，用于兜底）。
- 订阅失败与重试：通过统一的错误码与 LRO reason 字段，让控制平面可以按错误类型选择重试策略。

## 7 未来扩展点

- 完善 VA gRPC Watch 流接口，与 Controlplane `/api/subscriptions/{id}/events` SSE 完成闭环。
- 在更多节点引入可插拔实现（例如不同的预处理/后处理算子），通过配置实现无侵入扩展。
- 深化 Triton In-Process 集成，在保持回退链的前提下进一步降低延迟与拷贝。

本详细设计说明书与概要设计共同构成 `video-analyzer` 子项目的设计基线，后续变更（尤其是公共接口与行为语义）应同步更新本文与相关专题设计文档。
