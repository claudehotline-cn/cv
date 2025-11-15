# CONTEXT（2025-11-15，全局架构与文档重构）

本文件汇总当前对话中围绕“整体架构设计、订阅/LRO 管线、推理与多阶段 Graph、协议与存储设计、设计文档重构”的关键结论，作为理解本仓库及后续路线图的统一上下文。

---

## 一、系统与仓库概览

- **业务目标**：接入多路 RTSP 视频源，执行可配置的多阶段视觉分析（检测/跟踪/ReID 等），以 WebRTC/WHEP 向浏览器实时回传叠加画面，并提供训练与模型上线能力。
- **主要子项目与职责**：
  - `video-analyzer`（VA）：RTSP 解码（NVDEC/FFmpeg）、多阶段 Graph 执行、GPU 零拷贝推理（TensorRT/Triton In-Process）、后处理与叠加、H.264/NVENC 编码、WHEP 输出，对内暴露 `AnalyzerControl` gRPC 与少量调试 HTTP。
  - `controlplane`（CP）：唯一对外 HTTP 入口，负责 `/api/*` 与 `/whep`，对接 VA/VSM/Trainer，管理订阅 LRO、训练与模型仓库、控制与观测接口。
  - `video-source-manager`（VSM）：管理 RTSP 源配置，通过 gRPC `SourceControl` 与 CP 协作，并以 Restream 方式发布稳定 RTSP 端点，暴露 REST/SSE 供观测。
  - `web-front`：Vue+TS 前端，提供 Sources/Pipelines/AnalysisPanel/Training 等页面，仅访问 CP HTTP 与 `/whep`。
  - `model-trainer`：训练服务（FastAPI+PyTorch+MLflow），产出 ONNX/TensorRT plan 与 manifest，结合 MinIO/MySQL/MLflow 构成训练与部署闭环。
- **基础设施**：MySQL（`cv_cp`）、Redis（可选）、MinIO、MLflow、Prometheus/Grafana、GPU（推理+NVENC/NVDEC）。

---

## 二、控制平面与订阅/LRO 总体设计

订阅与播放从“控制平面与订阅”视角的整体结构如下：

```mermaid
flowchart LR
  WEB[Web-Front SPA] -->|"POST/GET/DELETE /api/subscriptions"| CP[Controlplane HTTP API]
  WEB -->|"SSE /api/subscriptions/:id/events"| CP
  WEB -->|"WHEP /whep"| CP

  subgraph CP_ZONE["Controlplane（控制平面）"]
    CP
    STORE[(订阅 Store / DB 映射)]
  end

  subgraph VA_ZONE["Video Analyzer（订阅执行与媒体）"]
    VAAPI[AnalyzerControl gRPC]
    LRO[LRO Runner / Operation / Step]
    PIPE[多阶段 Graph / 媒体管线]
  end

  subgraph VSM_ZONE["Video Source Manager"]
    VSM[SourceControl gRPC]
  end

  subgraph DATA["持久化与缓存"]
    DB[(MySQL cv_cp)]
    REDIS[(Redis)]
  end

  CP -->|gRPC Subscribe/Get/Cancel/Watch| VAAPI
  VAAPI --> LRO
  LRO --> PIPE

  CP -->|gRPC 源状态/配置| VSM
  VSM -->|Restream RTSP 源| PIPE

  CP -->|订阅/源/训练元数据| DB
  CP -->|可选配额/速率缓存| REDIS

  CP -->|WHEP 反向代理| PIPE
```

- **CP HTTP API**：
  - 订阅：`POST/GET/DELETE /api/subscriptions`，`GET /api/subscriptions/{id}/events`（SSE）。
  - 控制：`/api/control/apply_pipeline`、`/api/control/hotswap`、`/api/control/pipeline_mode` 等，经 CP 转发至 VA gRPC。
  - 训练与模型：`/api/train/*`、`/api/repo/*`。
  - 媒体：`POST/PATCH/DELETE /whep`，作为 VA WHEP 的反向代理与编排入口。
- **LRO 订阅执行（VA 内部）**：
  - `Runner/Operation/Step/IStateStore/AdmissionPolicy` 组成通用 LRO 框架；
  - 订阅由一系列步骤构成（打开 RTSP → 加载模型 → 构建/启动 pipeline → 准备 WHEP 输出），每个步骤有明确的 phase 与错误原因；
  - CP 通过 `AnalyzerControl` gRPC 触发订阅、查询 phase 与 timeline，并在 MySQL 中维护映射。
- **VSM 与源管理**：
  - VSM 通过 gRPC `SourceControl` 接收 CP 的源启停与配置变更；
  - 向 VA 提供 Restream RTSP 端点，避免 VA 直接依赖上游摄像头稳定性；
  - 详细协议见 `docs/design/protocol/VSM_REST_SSE与指标配置.md` 与 `控制平面HTTP与gRPC接口说明.md`。

---

## 三、推理、多阶段 Graph 与 GPU 零拷贝

- **多阶段 Graph 框架**（`multistage_graph_详细设计.md`）：
  - 核心抽象：`Packet/NodeContext/INode/Graph/NodeRegistry/AnalyzerMultistageAdapter`；
  - 支持条件边、join、ReID 平滑等高级节点，通过 YAML 描述 pipeline；
  - 新节点扩展需实现 `INode` 接口，并在 `NodeRegistry` 中注册。
- **推理引擎与集成**：
  - `tensorrt_engine.md`：介绍 VA 内部 TensorRT/ONNX Runtime session 管理与引擎抽象；
  - `triton_inprocess_integration.md`：以 In-Process 作为主路径，附录涵盖 gRPC 集成方案；
  - 配合 LRO 与 Graph，实现从 decode→预处理→推理→后处理→叠加的可配置管线。
- **GPU 零拷贝路径**（`zero_copy_execution_详细设计.md`）：
  - 解码：NVDEC 将帧解码到 GPU；
  - 预处理：CUDA kernel 完成 letterbox/resize，生成 NCHW FP32/FP16 tensor；
  - 推理：通过 IOBinding 将显存 buffer 直接绑定到 TensorRT/Triton；
  - 后处理：GPU decode + NMS，行为与 CPU 基线对齐，必要时可回退到 CPU NMS；
  - 提供 compare/suggest 脚本，用于校准 CPU/GPU 检测框差异与 conf/iou。

---

## 四、存储、协议与可观测性

- **存储设计**（`storage_详细设计.md`）：
  - 聚合原 `数据库设计.md` 内容，统一描述 MySQL `cv_cp` 的实体（sources/pipelines/graphs/models/sessions/events/logs/training_records 等）和 ER 图；
  - 说明 VA/CP 访问数据库的 `DbPool` 与各 `Repo` 模块职责，以及迁移策略与索引约定。
- **协议与错误码**（`protocol` 目录）：
  - `控制平面HTTP与gRPC接口说明.md`：系统性描述 CP HTTP API、CP↔VA `AnalyzerControl` gRPC、CP↔VSM `SourceControl` gRPC；
  - `webrtc-protocol.md`：描述 WHEP/WHEP 相关交互与实现注意事项；
  - `控制面错误码与语义.md`：统一 HTTP/gRPC/LRO 的错误码与 reason 语义。
- **可观测性**（`observability` 目录）：
  - `observability_详细设计.md` 作为日志与指标设计的单一权威文档，已整合原 LOGGING/METRICS/path 标签/PromQL/节流配置等内容；
  - Prometheus + Grafana 用于监控订阅链路、推理性能、训练与 DB 相关指标。

---

## 五、设计文档重构与约定

围绕 `docs/design` 目录，本次对话完成了系统性重构与整合：

- **子目录结构**：
  - `architecture/`：系统概要设计与各子系统详细设计（VA、CP、VSM、Web-Front）；
  - `subscription_pipeline/`：订阅流水线与 LRO 专题设计（`subscription_pipeline_详细设计.md`、`lro_subscription_design.md`）以及多阶段 Graph、推理引擎与 GPU 零拷贝；
  - `protocol/`：CP HTTP/gRPC、VSM REST/SSE、WebRTC/WHEP 等协议与错误码；
  - `storage/`：数据库与存储详细设计；
  - `observability/`：日志与指标设计（集中在 `observability_详细设计.md`）；
  - `training/`：训练流水线与模型仓库设计。
- **文档整合与删除**：
  - 将 `subscription_lro` 目录下的历史文档整合为 `subscription_pipeline/lro_subscription_design.md`，附录中保留早期异步订阅方案；
  - 将 `engine_multistage` 重命名并归档为 `subscription_pipeline`，统一承载多阶段 Graph 与引擎设计；
  - 将 `cp_vsm_protocol` 重命名并归档为 `protocol`，统一管理协议相关文档；
  - 将观测层散列文档（LOGGING/METRICS/path 标签/PromQL/节流配置等）整合进 `observability_详细设计.md` 并删除原文件；
  - 删除多份已过时或被合并的文档（如 `perf_guards.md`、早期前端设计稿等），以及废弃的 `subscription_lro/` 目录；
  - 删除废弃的 `web-frontend-old/` 工程，只保留 `web-front/` 作为唯一前端实现。
- **工作流与约束（摘录）**：
  - 修改代码与文档需使用 `apply_patch`；完成后在 `docs/memo` 追加当日记录；
  - 构建成功后必须进行测试；新增设计图统一使用 Mermaid；
  - 提交信息使用中文祈使句，保持变更聚焦与与 Issue 关联；沟通与文档语言统一为中文。

本 CONTEXT.md 与 `docs/design/architecture/整体架构设计.md`、`docs/context/ROADMAP.md` 共同构成后续演进与决策的全局参照。***
