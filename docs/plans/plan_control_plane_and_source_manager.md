# 控制平面与视频源管理推进计划（VA + VSM）

## 背景与目标
- 背景：依据 `docs/references/video-analyzer设计文档.md` 与 `docs/references/video-source-manager设计文档.md`，现有工程已完成多阶段 Analyzer、IoBinding、NVDEC/NVENC、WebRTC/REST 框架与部分控制平面骨架。
- 目标：
  - 短期（M1）：在 video-analyzer 内完善控制平面最小闭环，稳定多阶段执行与端到端可观测；在 video-source-manager 实现源的注册/健康检查与基础 API。
  - 中期（M2）：打通 VA 与 VSM 的双向对接，实现基于源状态的自动 Pipeline 编排与运维配置；端到端稳定可用。
  - 中长（M3）：将控制平面独立化（可选嵌入/独立两种形态），增强批量编排、滚动变更与跨实例调度。

## 现状（已完成对齐）
- 多阶段 Graph：YAML 构建、条件边（when/when_not）、join、核心节点（preproc/model/nms/overlay/kpt/roi.batch）。
- ORT 集成：IoBinding、模型真实输出名自动映射、GPU 路径（可选编译 CUDA kernels），失败兜底 CPU。
- 日志与节流：全局/分标签节流与级别桥接；已成文档与示例。
- 运行链路：NVDEC/NVENC、WebRTC signaling/transport、REST 引擎/图切换。
- 控制平面：embedded 目录、gRPC Server 骨架（宏控），CMake 可选构建。

## 范围与边界
- 控制平面（短期内嵌于 video-analyzer，后续可拆）：暴露编排/查询接口，统一 REST/GRPC 接入。
- video-source-manager：负责源生命周期、健康度与属性管理；对外 API 与事件；对 VA 提供可订阅的源状态。
- video-analyzer：专注多阶段执行与媒体出入口，按控制平面/源事件拉起或停止 Pipeline。

## 里程碑与任务

### M1 基线闭环（1–2 天）
video-analyzer
- Application 从 `app.yaml` 自动启动控制平面与 REST/Signaling（读取 `control_plane.enabled/grpc_addr`，支持 env 覆盖）；完善启动/关闭生命周期。
- gRPC 服务：AnalyzerControl 最小集（ApplyGraph/SetEngine/SubscribePipeline/QueryRuntime）；参数透传 EngineOptions 与 GraphID/YAML 路径。
- NodeNms 阈值贯通：将图中 `conf/iou` 传递至 CPU/CUDA 后处理，移除对环境变量阈值的隐式依赖。
- RuntimeSummary：多阶段 NodeModel open 后已回填；首次 open_all 后补打印一次摘要。

video-source-manager
- 源注册与内存存储：Add/Update/Delete/List/Describe；字段含 `uri/auth/tags/profiles/decoder_pref`。
- 健康探测器：RTSP OPTIONS/DESCRIBE + 首帧探测，超时/重试/退避；记录 `last_ok/fail_reason`。
- gRPC/REST：SourceService（Add/Remove/List/Describe/Health），事件订阅（SourceState）。
- 简易持久化：JSON/YAML（启动加载，变更落盘；后续可换 sqlite）。

验收
- 后端启动自动就绪；通过 gRPC/REST 可切图/改引擎；前端可连上 8083；M1 完成后可观测（/healthz,/readyz,/metrics）。

### M2 端到端打通（2–3 天）
- video-analyzer ↔ video-source-manager 对接：
  - VA 启动后从 VSM 拉活跃源列表，按 profile 订阅生成 Pipeline（幂等、可复用）。
  - 事件桥：源状态 up -> 启动；down -> 停止（内嵌模式直调；分进程模式通过 gRPC）。
- 配置与可运维：
  - `app.yaml` 增加 signaling/control_plane/grpc 端口与端点；env 覆盖优先级定义。
  - 统一错误码/原因短语（INVALID_ARG/NOT_FOUND/ALREADY_EXISTS/UNAVAILABLE/INTERNAL）。
  - Metrics 健全：流数/订阅数/帧率/延迟/掉线。

验收
- 前端发起订阅后 30s 内可见帧（无流时至少连接成功）；源上下线联动对应 Pipeline 创建/销毁；异常路径有报错与自愈日志。

### M3 拆分与增强（3–5 天）
- 控制平面外置：独立 project，保持 API 不变；video-analyzer 持续支持“内嵌/外置”两种模式。
- 批量/编排：批量 ApplyPipelines、滚动重载图，跨实例分配（先实现简单策略与接口预留）。
- source-manager 增强：密文存储、限流/重连策略、标签/项目级聚合视图。

## 详细任务清单

### video-analyzer
- 控制平面自启与生命周期
  - `src/app/application.cpp`：解析 `control_plane.enabled/grpc_addr`，构造/启动/关闭 gRPC；REST 与 gRPC 参数桥接。
- gRPC AnalyzerControl 最小集
  - `ApplyGraph/SetEngine/SubscribePipeline/QueryRuntime/GetModels/ListPipelines`；错误语义统一；返回运行时摘要。
- 多阶段一致性
  - `node_nms.cpp/postproc_yolo_det.*`：阈值参数贯通；GPU 失败兜底 CPU 已具备。
  - `node_model.cpp`：open 后回填 EngineRuntime；`open_all` 成功后打印一次 RuntimeSummary。
- WebRTC 信令
  - `transport_webrtc_datachannel.cpp`：已支持 `VA_SIGNAL_PORT/VA_SIGNAL_ENDPOINT`；在 `app.yaml` 增加对应配置与 env 覆盖说明。
- 文档
  - `docs/references`：实现对照表、使用指南、端口与覆盖优先级。

### video-source-manager
- registry：内存 + YAML/JSON 落盘；并发访问安全。
- health_checker：异步探测，超时/退避/重试；失败原因与时间戳统计。
- profiles：编码/发布配置模板；与 VA profile 对齐。
- API：gRPC/REST 同构（Add/Update/Delete/List/Describe/Health/WatchState）。
- 事件：SourceState 订阅（支持 since 与最近 N 条回放）。
- 运维：`vsm.yaml`（监听地址、并发探测数、失败退避、默认 profiles）；日志节流与级别对齐 VA。

## 接口契约（摘要）

AnalyzerControl（gRPC/REST）
- `ApplyGraph(graph_id|yaml_path, engine_options)`
- `CreatePipeline(source_id, profile_id, graph_id, options)` / `StartPipeline` / `StopPipeline`
- `SetEngine(options)` / `QueryRuntime()` / `ListPipelines()` / `GetModels()`

SourceService（gRPC/REST）
- `AddSource(id, uri, auth, tags, profiles)` / `UpdateSource` / `RemoveSource`
- `ListSources()` / `DescribeSource(id)` / `Health(id)`
- `WatchSourceState(since)` -> stream<State>

错误与版本
- 错误码：INVALID_ARG/NOT_FOUND/ALREADY_EXISTS/UNAVAILABLE/INTERNAL；均返回 `reason/message`。
- 版本：在响应 meta 中返回服务版本与 schema 版本（便于演进）。

## 配置与优先级
- `app.yaml` / `vsm.yaml` 中显式配置优先；关键端口/日志节流支持 env（VA_*）覆盖；REST/控制面可热更新 engine.options。
- 端口：REST(8082)、signaling(8083，支持 `VA_SIGNAL_PORT/VA_SIGNAL_ENDPOINT`)、gRPC（配置声明）。

## 验收与测试
- Smoke 测试：
  - 后端：`/api/system/info`、`/api/models`、`/api/engine/set`、`/api/graph/set`。
  - 源管：`Add/List/Health` 与事件流；对接 VA 创建/销毁 Pipeline。
- E2E：前端 WebRTC 连接成功；30s 内可见帧（或连接成功但提示无源）。
- Metrics：/metrics 报文包含帧率、延迟、连接数、掉线数。

## 风险与回滚
- gRPC 依赖差异：使用宏控/可选构建；失败回退 REST-only。
- CUDA kernels：保持可选（WITH_CUDA_KERNELS）；无 nvcc 时退回 D2H+CPU NMS。
- 端口冲突：支持 env 覆盖；前端信令地址可配置，避免硬编码。

## 时间预估与责任人（占位）
- M1：1–2 天（VA ⅔，VSM ⅓）
- M2：2–3 天（对接与配置/运维）
- M3：3–5 天（外置化与增强）

