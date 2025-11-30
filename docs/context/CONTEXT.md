# CONTEXT（2025-11-30，cp-spring 完全接管 C++ CP 现状）

本文件梳理 **controlplane-spring（cp-spring） 完整接管 C++ ControlPlane** 后的整体状态，覆盖架构、API 迁移范围、Docker 拓扑与测试结论，作为后续运维与演进的统一上下文。

---

## 一、总体目标与当前达成度

- 目标：用 cp-spring 完全替代 C++ 版 ControlPlane，对前端、Agent 与脚本透明，C++ CP 仅作为可选回退，不再承载生产流量。
- 达成度：
  - cp-spring 已在 Docker 中以 `cv/cp-spring:latest` 运行并暴露 `18080`，是唯一对外 CP 入口。
  - C++ `cp` 容器保留但不暴露端口，不再被 web 或 agent 依赖。
  - `controlplane/test/scripts` 下的关键 Python 回归脚本全部在 cp-spring 下 PASS。
  - web 前端与 Agent 均通过环境变量指向 cp-spring。

---

## 二、架构与部署拓扑（Docker 视角）

- 技术栈：Spring Boot 3.1.x + Java 21 + Maven。
- gRPC 通道：
  - `VideoAnalyzerClient`：通过 `CP_VA_GRPC_ADDR=va:50051` 调用 VA `AnalyzerControl` 服务，封装订阅、管线控制、Repo 管理与转换等 RPC。
  - `VideoSourceManagerClient`：通过 `CP_VSM_GRPC_ADDR=vsm:7070` 调用 VSM `SourceControl` 服务，封装 Attach/Detach/Update/GetHealth/WatchState。
- 数据层：
  - 使用 MyBatis-Plus 访问 MySQL `cv_cp`，实体包括 `sources/pipelines/graphs/models/train_jobs/events/logs` 等。
- Docker compose 拓扑：
  - `cp-spring`：暴露 `18080:18080`，环境中配置 VA/VSM/DB 地址；healthcheck 使用 `/api/system/info`。
  - `web`：依赖 `cp-spring`，通过 `VITE_API_BASE=http://cp-spring:18080` 和 `VITE_CP_BASE_URL=http://cp-spring:18080` 访问 CP。
  - `agent`：使用 `AGENT_CP_BASE_URL=http://cp-spring:18080` 调用 `/api/agent/threads/{id}/invoke`。
  - `cp`（C++）：仍构建但不暴露端口，仅在内部网络中存在，作为回退/对比工具。

---

## 三、API 迁移覆盖范围

### 3.1 核心业务接口

- 系统与配置：
  - `/api/system/info`：返回 `restream.rtsp_base` 等基础信息（Caffeine 缓存）。
  - `/api/models`：从 DB 读取模型元数据，结构兼容 C++ CP。
  - `/api/pipelines`：通过 `PipelineReadService` 列出管线。
  - `/api/graphs`：通过 `GraphReadService` 列出图配置，供 GUI 选择。

- 订阅与源管理：
  - `/api/subscriptions`（POST/GET/DELETE）与 `/api/subscriptions/{id}/events` SSE：支持 query+JSON 混合、ETag/304、`demo-id` 501 占位、`CP_FAKE_WATCH` 模式。
  - `/api/sources:attach|:detach|:enable|:disable`、`/api/sources`、`/api/sources/watch_sse`：完全通过 VSM gRPC 实现，与 Python 脚本行为契合。

- 控制与编排：
  - `/api/control/apply_pipeline/apply_pipelines/drain/remove_pipeline/hotswap/set_engine/pipelines`：封装 VA 控制 RPC。
  - `/api/orch/attach_apply/detach_remove/health`：编排端点；`attach_apply` 支持仅传 `source_id` 时基于 `cp.restream.rtsp_base` 拼 RTSP URI。

### 3.2 Repo 与训练管理

- Repo 管理：
  - `/api/repo/load/unload/poll/remove/upload/add/list/config`：经 gRPC 调 VA 的 RepoLoad/Unload/Poll/List/GetConfig/SaveConfig/PutFile/RemoveModel。
  - `/api/repo/convert_upload/convert/cancel/convert/events`：封装 VA RepoConvertUpload/Cancel/Stream，用于 ONNX → TensorRT 转换与进度观察。

- 训练管理：
  - `/api/train/start/status/list/deploy/artifacts/artifacts/download`：通过 `CP_TRAINER_BASE_URL` 代理 trainer 服务；`/api/train/start` 会在返回中补写 `data.events="/api/train/events?id=..."`。
  - `/api/train/events`：SSE 代理训练事件流；trainer 不可用时返回 `TRAINER_UNAVAILABLE` 事件。

### 3.3 Agent、调试与观测

- Agent 代理：
  - `/api/agent/threads/{threadId}/invoke`：从 `cp.agent.base-url` 或 `CP_AGENT_BASE_URL` 解析 Agent 地址，将请求代理到 `/v1/agent/threads/{id}/invoke`，在 body `messages` 前插入 system 提示，并通过 `AuditLogger` 记录 request/response/error。

- 调试接口：
  - `/api/_debug/echo`：回显 `path`。
  - `/api/_debug/sub/get`：返回 `{id, found=false}` 的占位结构。
  - `/api/_debug/db`：返回 `{"errors":{last_error?}, "cfg":{driver,host,port,user,schema,connected}}`，用于快速检查 DB 连接状态。

- 观测与兼容性：
  - `/metrics`：`MetricsAliasController` 使用 `RestTemplate` 代理到 `/actuator/prometheus`，为前端与 Prometheus 保留 C++ CP 的 `/metrics` 路径。
  - `/api/events/stream`：通用 SSE 心跳流。
  - `/api/events/recent`：返回 `{"code":"OK","data":{"items":[],"next":0}}` 的占位结构，保持前端兼容。

---

## 四、测试与验证

- 在 `CP_BASE_URL=http://127.0.0.1:18080` 环境下，以下脚本已在 cp-spring 上稳定 PASS：
  - `check_cp_system_info.py`
  - `check_cp_min_api_once.py`
  - `check_cp_json_negative.py`
  - `check_cp_sse_placeholder.py`
  - `check_cp_sse_watch.py`（`CP_TEST_PROFILE=det_720p`）
  - `check_cp_sources_watch_sse.py`
  - `check_cp_sources_attach_detach.py`
  - `check_cp_sources_enable_disable.py`
  - `check_cp_orch_attach_apply.py`
  - `check_cp_orch_detach_remove.py`
  - `check_cp_orch_health.py`
- `/metrics` 返回 Prometheus 文本；`/api/events/recent` 返回空列表；前端 `dataProvider.metrics*` 与 `eventsRecent` 仍可正常工作。

---

## 五、C++ CP 下线状态与后续建议

- C++ CP 已从以下路径上退出生产：
  - 不再对外暴露端口；
  - `web` 与 `agent` 仅依赖 cp-spring；
  - 所有脚本与配置均以 cp-spring 为主。
- 后续建议：
  - 如无遗留系统直接访问 `cp:18080`，可在 compose 中移除 `cp` 服务，或单独维护一个仅用于对比/回归的 C++ CP 环境。
  - 所有新特性与调试接口优先在 cp-spring 中实现，并同步更新本 CONTEXT 与 ROADMAP。
