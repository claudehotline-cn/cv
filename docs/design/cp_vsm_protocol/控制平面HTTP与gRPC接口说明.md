# 控制平面 HTTP API 与 gRPC 接口说明

> 适用范围：`controlplane/` 子项目对外暴露的 HTTP API，以及 Controlplane 与 VA / VSM 之间的 gRPC 接口。  
> 详细的内部架构与数据结构请参考 `docs/design/architecture/controlplane_design.md` 与各 proto 文件。

## 1 总览

- HTTP 入口：
  - 基础路径：`/api/*`，对 Web-Front 与脚本开放。
  - 媒体出口：`/whep`（WHEP 下行媒体），参见 `webrtc-protocol.md`。
- gRPC 连接：
  - CP → VA：`va.v1.AnalyzerControl`（订阅、管线、引擎与模型仓库控制）。
  - CP → VSM：`vsm.v1.SourceControl`（源 attach/状态/启停）。
- 错误与语义：
  - HTTP 返回体统一格式与错误码语义见 `控制面错误码与语义.md`。
  - gRPC Status 与 `code` 字段保持一致。

后续如新增 API，应优先在本文件中补充条目，再在架构/详细设计文档中展开实现细节。

## 2 Controlplane HTTP API（对外）

本节按功能分组列出当前 Controlplane 暴露的 HTTP API，并给出其与底层 gRPC 的关系。

### 2.1 订阅与播放

| 方法 | 路径                                   | 说明                                                | 主要后端调用                         |
|------|----------------------------------------|-----------------------------------------------------|--------------------------------------|
| POST | `/api/subscriptions`                  | 创建订阅；生成 `cp_id` 并触发 VA 订阅管线          | `AnalyzerControl.SubscribePipeline`  |
| GET  | `/api/subscriptions/{id}`             | 查询订阅状态；支持 ETag/304                         | CP 内部 `Store` + VA `GetStatus/QueryRuntime` |
| DELETE | `/api/subscriptions/{id}`           | 取消订阅；幂等                                      | `AnalyzerControl.UnsubscribePipeline` |
| GET  | `/api/subscriptions/{id}/events`      | 订阅阶段事件 SSE（规划中）                          | `AnalyzerControl.Watch`              |
| GET  | `/whep`（含查询参数）                 | WHEP 媒体出口；向前端输出 H.264 RTP                | HTTP 代理到 VA / 内部 WHEP 终端       |

请求/响应字段与阶段语义详见：

- 订阅整体设计：`docs/design/subscription_lro/lro_subscription_design.md`
- 前端分析面板时序：`docs/design/architecture/web_front_analysis_panel_详细设计.md`

### 2.2 源管理

| 方法 | 路径                            | 说明                                               | 主要后端调用                   |
|------|---------------------------------|----------------------------------------------------|--------------------------------|
| GET  | `/api/sources`                 | 聚合所有视频源（VSM WatchState / GetHealth）      | `SourceControl.WatchState/GetHealth` |
| POST | `/api/sources:enable`         | 启用指定 source（例如写入 enabled=true）          | `SourceControl.Update`         |
| POST | `/api/sources:disable`        | 禁用指定 source（例如写入 enabled=false）         | `SourceControl.Update`         |

CP 将 `source_id` 与 `restream_rtsp_base` 组合为稳定的 Restream URL（默认 `rtsp://127.0.0.1:8554/{source_id}`），并在订阅时向 VA 传递该 URL。

### 2.3 引擎与管线控制

| 方法 | 路径                               | 说明                                                                  | 主要后端调用                             |
|------|------------------------------------|-----------------------------------------------------------------------|------------------------------------------|
| POST | `/api/control/apply_pipeline`     | 下发或更新 Pipeline 规格（YAML/模板等）；用于配置分析拓扑             | `AnalyzerControl.ApplyPipeline/ApplyPipelines` |
| POST | `/api/control/remove_pipeline`    | 移除指定 Pipeline                                                     | `AnalyzerControl.RemovePipeline`        |
| POST | `/api/control/hotswap`            | 热切换指定 Pipeline 节点的模型                                       | `AnalyzerControl.HotSwapModel`         |
| POST | `/api/control/drain`              | 对指定 Pipeline 执行 drain（处理完在途帧后停止）                      | `AnalyzerControl.Drain`                |
| GET  | `/api/control/pipelines`          | 列出当前 Pipeline 状态（流、FPS、错误等）                            | `AnalyzerControl.ListPipelines`        |
| POST | `/api/control/set_engine`         | 更新 VA 推理引擎配置（provider/device/options）                      | `AnalyzerControl.SetEngine`            |
| GET  | `/api/va/runtime`                 | 查询 VA 运行时信息（当前 provider/gpu_active/io_binding 等）         | `AnalyzerControl.QueryRuntime`         |

具体字段结构参见 `video-analyzer/proto/analyzer_control.proto` 与 `tensorrt_engine.md`。

### 2.4 训练与模型仓库

训练 API 由 CP 统一转发到 Trainer 服务或 VA 模型仓库控制接口，典型端点包括：

| 方法 | 路径                        | 说明                                           | 主要后端调用/代理              |
|------|-----------------------------|------------------------------------------------|--------------------------------|
| POST | `/api/train/start`         | 发起训练任务                                   | Trainer HTTP API / 内部服务    |
| GET  | `/api/train/jobs`          | 列出训练任务及状态                             | Trainer API / 数据库           |
| POST | `/api/train/deploy`        | 部署训练完成的模型（受门禁控制）               | `AnalyzerControl.Repo*` / CP 内部逻辑 |
| GET  | `/api/repo/models`         | 列出仓库中的模型与版本                         | `AnalyzerControl.RepoList`     |
| POST | `/api/repo/load`           | 加载模型到 VA 运行时                           | `AnalyzerControl.RepoLoad`     |
| POST | `/api/repo/unload`         | 从 VA 运行时卸载模型                           | `AnalyzerControl.RepoUnload`   |
| POST | `/api/repo/convert_upload` | 上传 ONNX 并触发转换为 TensorRT plan           | `AnalyzerControl.RepoConvertUpload` |
| GET  | `/api/repo/convert_stream` | 监听转换日志与进度（SSE 或 chunked 传输）      | `AnalyzerControl.RepoConvertStream` |

> 说明：具体训练门禁策略与部署流程详见 `cv_训练流水线（training_pipeline）详细设计_v_1.md`。

### 2.5 观测与调试

| 方法 | 路径                         | 说明                                               | 后端实现                |
|------|------------------------------|----------------------------------------------------|-------------------------|
| GET  | `/api/system/info`          | 聚合 VA/ VSM / DB / Trainer 等组件的系统信息      | CP 内部 `cache` + gRPC/DB |
| GET  | `/api/_metrics/summary`     | CP 侧 metrics 汇总视图（请求量、延迟、错误等）    | CP 内部 `metrics.cpp`   |
| GET  | `/api/_debug/db`            | 数据库连通性与错误快照                            | CP 内部 `db.cpp`        |

其中 `/metrics`（Prometheus 文本）通常由 VA 直接暴露，CP 可按需要代理或聚合。

## 3 CP ↔ VA gRPC 接口（AnalyzerControl）

proto 文件：`video-analyzer/proto/analyzer_control.proto`  
命名空间：`va.v1`

### 3.1 服务定义

```proto
service AnalyzerControl {
  rpc ApplyPipeline(ApplyPipelineRequest) returns (ApplyPipelineReply);
  rpc ApplyPipelines(ApplyPipelinesRequest) returns (ApplyPipelinesReply);
  rpc RemovePipeline(RemovePipelineRequest) returns (RemovePipelineReply);
  rpc HotSwapModel(HotSwapModelRequest) returns (HotSwapModelReply);
  rpc Drain(DrainRequest) returns (DrainReply);
  rpc GetStatus(GetStatusRequest) returns (GetStatusReply);
  rpc SubscribePipeline(SubscribePipelineRequest) returns (SubscribePipelineReply);
  rpc UnsubscribePipeline(UnsubscribePipelineRequest) returns (UnsubscribePipelineReply);
  rpc SetEngine(SetEngineRequest) returns (SetEngineReply);
  rpc QueryRuntime(QueryRuntimeRequest) returns (QueryRuntimeReply);
  rpc ListPipelines(ListPipelinesRequest) returns (ListPipelinesReply);
  rpc Watch(WatchRequest) returns (stream PhaseEvent);
  rpc RepoLoad(RepoLoadRequest) returns (RepoLoadReply);
  rpc RepoUnload(RepoUnloadRequest) returns (RepoUnloadReply);
  rpc RepoPoll(RepoPollRequest) returns (RepoPollReply);
  rpc RepoList(RepoListRequest) returns (RepoListReply);
  rpc RepoGetConfig(RepoGetConfigRequest) returns (RepoGetConfigReply);
  rpc RepoSaveConfig(RepoSaveConfigRequest) returns (RepoSaveConfigReply);
  rpc RepoPutFile(RepoPutFileRequest) returns (RepoPutFileReply);
  rpc RepoConvertUpload(RepoConvertUploadRequest) returns (RepoConvertUploadReply);
  rpc RepoConvertStream(RepoConvertStreamRequest) returns (stream RepoConvertEvent);
  rpc RepoConvertCancel(RepoConvertCancelRequest) returns (RepoConvertCancelReply);
  rpc RepoRemoveModel(RepoRemoveModelRequest) returns (RepoRemoveModelReply);
}
```

### 3.2 功能分组与典型映射

- **管线控制：**
  - `ApplyPipeline/ApplyPipelines/RemovePipeline/HotSwapModel/Drain/GetStatus/ListPipelines`。
  - 对应 HTTP：`/api/control/apply_pipeline`、`/api/control/remove_pipeline`、`/api/control/hotswap`、`/api/control/drain`、`/api/control/pipelines`。
- **订阅数据面：**
  - `SubscribePipeline/UnsubscribePipeline`：在 VA 内部创建/销毁分析 Pipeline（数据面订阅）。
  - 对应 HTTP：`POST/DELETE /api/subscriptions`。
  - `Watch`：流式输出订阅阶段事件，供 SSE `/api/subscriptions/{id}/events` 对接。
- **引擎配置与运行时：**
  - `SetEngine`：设置推理引擎 provider/device/options。
  - `QueryRuntime`：查询当前运行时（provider/gpu_active/io_binding/device_binding）。
  - 对应 HTTP：`POST /api/control/set_engine`、`GET /api/va/runtime`。
- **模型仓库与训练辅助：**
  - `RepoLoad/RepoUnload/RepoPoll/RepoList/RepoGetConfig/RepoSaveConfig/RepoPutFile/RepoConvert* /RepoRemoveModel`：
    - 管理模型仓库加载状态、配置文件与工件上传/转换。
  - 对应 HTTP：`/api/repo/*`、部分训练部署 API。

各消息字段语义详见 proto 文件；错误码与 HTTP 状态映射遵循 `控制面错误码与语义.md`。

## 4 CP ↔ VSM gRPC 接口（SourceControl）

proto 文件：`video-source-manager/proto/source_control.proto`  
命名空间：`vsm.v1`

### 4.1 服务定义

```proto
service SourceControl {
  rpc Attach(AttachRequest) returns (AttachReply);
  rpc Detach(DetachRequest) returns (DetachReply);
  rpc GetHealth(GetHealthRequest) returns (GetHealthReply);
  rpc WatchState(WatchStateRequest) returns (stream WatchStateReply);
  rpc Update(UpdateRequest) returns (UpdateReply);
}
```

### 4.2 功能分组与典型映射

- **源生命周期管理：**
  - `Attach/Detach`：为兼容阶段保留的 attach/Detach 能力，通常与旧 API 或运维脚本配合使用。
  - CP 在 Restream 模式下更推荐通过配置与 `Update` 控制启停，而非频繁 Attach/Detach。
- **健康检查与状态：**
  - `GetHealth`：一次性返回当前所有流的统计（FPS、RTT、丢包率、phase 等）。
  - `WatchState`：周期性流式返回 SourceItem 列表，用于驱动 `/api/sources` 与前端源列表。
- **配置更新：**
  - `Update`：根据 `attach_id` 更新源的 options（如 enabled/profile/model_id 等）。
  - 对应 HTTP：`/api/sources:enable`、`/api/sources:disable` 以及后续扩展的源属性更新接口。

## 5 错误码与返回体约定

- 所有 CP HTTP API 返回形如：
  - 成功：`{"success":true,"code":"OK","data":{...}}`
  - 失败：`{"success":false,"code":"<ERROR_CODE>","message":"..."}`
- HTTP 状态码与 `code` 映射：
  - `200/201/204 → OK`；`400 → INVALID_ARG`；`404 → NOT_FOUND`；`409 → ALREADY_EXISTS`；`429 → UNAVAILABLE`；`503 → UNAVAILABLE`；`500 → INTERNAL`。
- gRPC 端：
  - 按 `StatusCode = INVALID_ARGUMENT/NOT_FOUND/ALREADY_EXISTS/UNAVAILABLE/INTERNAL` 等返回；
  - Reply 内不再使用额外布尔字段表达是否成功，客户端以 Status 为准。

更多示例与客户端重试建议见 `控制面错误码与语义.md`。

## 6 参考资料

- 架构与流程：
  - `docs/design/architecture/整体架构设计.md`
  - `docs/design/architecture/controlplane_design.md`
- 协议与接口：
  - `docs/design/cp_vsm_protocol/VSM_REST_SSE与指标配置.md`
  - `docs/design/cp_vsm_protocol/webrtc-protocol.md`
  - `docs/design/cp_vsm_protocol/控制面错误码与语义.md`
- 订阅与训练：
  - `docs/design/subscription_lro/lro_subscription_design.md`
  - `docs/design/training/cv_训练流水线（training_pipeline）详细设计_v_1.md`

## 附录 A：早期嵌入式控制平面与 VSM 集成雏形（历史）

> 本附录基于历史文档《控制平面与 VSM 集成说明（阶段A雏形）》提炼要点，用于保留 VA 内嵌控制面阶段的背景信息。当前推荐架构为独立 `controlplane/` 进程，本附录仅做对照参考。

### A.1 架构背景

- 早期版本中，控制平面能力内嵌在 VA 进程中：
  - 控制面目录：`video-analyzer/src/control_plane_embedded/`
  - 提供最小 gRPC/REST 能力：Apply/Remove/Drain/HotSwap/GetStatus 等。
  - 暴露 Prometheus `/metrics` 与部分调试 HTTP 接口。
- VSM 作为独立进程，负责：
  - RTSP 源管理与健康检查；
  - 通过 gRPC `SourceControl` 与 VA 通信（Attach/Detach/WatchState/Update）。

### A.2 关键目录与组件

- VA 侧嵌入式控制面（已由独立 Controlplane 替代）：
  - `interfaces.hpp`：Status/OpaquePtr/PlainPipelineSpec/IGraphAdapter/IExecutor 接口。
  - `adapters/graph_adapter_yaml.*`：从 `config/graphs/*.yaml` 构建多阶段 Graph。
  - `controllers/pipeline_controller.*`：封装 Apply/Remove/Drain/HotSwap/GetStatus 操作。
  - `api/grpc_server.*`：`AnalyzerControl` gRPC 服务实现雏形。
  - `exporters/prometheus_exporter.*`：导出 VA 控制面相关指标到 `/metrics`。
  - `io/from_vsm_link.hpp`：与 VSM 的数据输入链路占位（可演进为共享内存/IPC/gRPC）。
- VSM 侧：
  - `proto/source_control.proto`：`SourceControl` gRPC 接口（Attach/Detach/GetHealth/WatchState/Update）。
  - `src/app/*`：VSM 主程序与适配器实现。

### A.3 配置与演进计划（摘要）

- VA 配置示例（历史）：

```yaml
control_plane:
  enabled: true
  grpc_addr: "0.0.0.0:50051"
  metrics_enabled: true
```

- 演进方向（当时的 B/C 阶段规划）：
  - 统一管理 gRPC 与 proto：
    - 在 `video-analyzer/proto/` 中维护 `analyzer_control.proto`、`pipeline.proto`。
    - CMake 强制 `find_package(Protobuf)`、`find_package(gRPC)`，并通过 vcpkg 管理依赖。
  - 执行器演进：
    - 用可扩展 Runner 替换简单执行器，支持热切换与 drain。
  - VSM 互通：
    - 利用 `SourceControl` gRPC 提供源健康检查与启停能力；
    - 向 VA 暴露的 `ToAnalyzerLink` 可按需要选择共享内存/IPC/gRPC。

### A.4 与当前架构的关系

- 当前独立 Controlplane 已接管大部分 HTTP 与协调能力：
  - 前端只与 CP 通信，VA/VSM 通过 gRPC 接入 CP。
  - 嵌入式控制面中的大部分职责已迁移到 `controlplane/src/server/*` 模块。
- 保留本附录的目的：
  - 追踪控制面能力从 VA 内嵌形态演进到独立 CP 的历史；
  - 便于理解 `AnalyzerControl` 与 `SourceControl` 在 VA/VSM 中的起源及代码布局。

