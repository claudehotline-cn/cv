# controlplain 设计（无桥接 + Restream 订阅）

> 本文在概要设计的基础上，详细说明 controlplane（CP）的内部模块、关键数据结构与订阅/训练等核心流程。  
> 外部整体架构与上下文请参考 `docs/design/architecture/整体架构设计.md`。

## 1 目标与边界

- 独立控制平面 `controlplain`：前端仅与 CP 通信；CP ↔ VA/VSM 通过 gRPC。
- 无桥接：CP 不做 REST 透传或短轮询；CP 生成 `cp_id` 并维护 timeline/ETag/SSE，作为唯一事实来源（SSOT）。
- 订阅改造为 Restream：VSM 启动即自拉上游并“再发布”为稳定端点；VA 订阅只拉取该端点进行分析。

## 2 架构视图

### 2.1 组件架构

```mermaid
flowchart LR
  FE[Web Front] -- HTTP/REST+SSE --> CP[controlplain]
  CP -->|gRPC| VA[Video Analyzer]
  CP -->|gRPC| VSM[Video Source Manager]
  subgraph CP_INTERNAL
    HTTP[server.http]
    CLI[clients.grpc]
    STORE[core.store cp_id_state]
    SSE[core.sse]
    OBS[obs.metrics]
    CFG[config]
  end
  HTTP --> STORE --> SSE
  HTTP --> CLI --> VA
  HTTP --> CLI --> VSM
  OBS -.-> HTTP
```

### 2.2 模块划分

CP 代码主要位于 `controlplane/src/`，按功能划分为：

- `server/http_server.cpp`：最小 HTTP 服务器与路由分发。
- `server/main.cpp`：主请求处理逻辑，解析路径与方法，将请求路由到具体 handler。
- `server/grpc_clients.cpp`：VA/VSM gRPC 客户端封装（`make_va_stub/make_vsm_stub` 等）。
- `server/store.cpp`：订阅状态存储（`Store` 单例，见 3.1）。
- `server/db.cpp`：数据库访问与训练相关 SQL（MySQL X DevAPI / ODBC）。
- `server/metrics.cpp`：CP 内部指标收集与导出。
- `server/cache.cpp`：简单缓存，用于 system info 等只读聚合结果。
- `server/http_proxy.cpp`：HTTP 代理工具，用于 `/whep` 与 Trainer API 代理。
- `server/watch_adapter.cpp`：与 VSM WatchState 的适配层。
- `config.cpp/config.hpp`：应用配置加载与结构定义（见 3.2）。

## 3 关键数据结构

### 3.1 订阅状态存储（Store）

头文件：`controlplane/include/controlplane/store.hpp`  
实现：`controlplane/src/server/store.cpp`

- `Store` 为进程内单例，负责维护订阅的轻量状态：
  - `SubscriptionRecord`：
    - `cp_id`：Controlplane 生成的订阅 ID（作为 `/api/subscriptions/{id}` 路径的一部分）。
    - `stream_id` / `profile` / `source_uri` / `model_id`：前端请求的规格。
    - `va_subscription_id`：VA 侧 pipeline/订阅标识，用于通过 gRPC 查询运行态。
    - `last`：最近一次 timeline 事件（phase、ts_ms、reason）。
    - `version`：版本号，用于生成弱 ETag。
  - 核心方法：
    - `create(stream_id, profile, source_uri, model_id, va_subscription_id)`：创建记录并返回 `cp_id`。
    - `get(cp_id)`：读取当前记录。
    - `set_phase(cp_id, phase, reason)`：更新阶段与原因，同时 bump `version`。
    - `erase(cp_id)`：删除记录（可作为 TTL 或清理策略的一部分）。
    - `make_etag(record)`：生成弱 ETag（`W"<version>"`）。

### 3.2 配置结构（AppConfig）

头文件：`controlplane/include/controlplane/config.hpp`  
实现：`controlplane/src/server/config.cpp`

- `AppConfig` 通过 `load_config` 从配置目录加载，主要字段包括：
  - `http_listen`：HTTP 监听地址（如 `0.0.0.0:8080`）。
  - `va_addr` / `vsm_addr`：VA/VSM gRPC 地址。
  - `sfu_whep_base` / `sfu_whep_default_variant` / `sfu_pause_policy`：前端 WHEP 提示信息。
  - `restream_rtsp_base`：Restream RTSP 前缀（例如 `rtsp://127.0.0.1:8554/`）。
  - `security`：安全配置（CORS、Bearer Token、速率限制）。
  - `va_tls` / `vsm_tls`：与 VA/VSM 通信的 TLS 参数。
  - `sse`：SSE 相关选项（keepalive、idle-close 等）。
  - `db`：数据库连接配置（driver、mysqlx_uri、host/port/user/password/schema 等）。
  - `trainer_base_url` / `deploy_gates`：外部 Trainer 服务与部署门禁配置。

## 4 订阅流程（Restream 模式）

- VSM 启动：从数据库读取“已启用”源，attach 并以 Restream 方式对每个源发布稳定端点（默认 `rtsp://127.0.0.1:8554/{source_id}`），维护 Ready/Backoff/Failed 与 FPS/err 指标，流式输出 WatchState。
- 前端分析页：列出所有源与状态，仅允许对“开启且 Ready”的源发起订阅。
- CP 订阅：POST `/api/subscriptions` 支持 `source_id`；如未显式提供 `source_uri`，由 CP 转译为 `restream.rtsp_base + source_id`，调用 VA SubscribePipeline；返回 `202+Location`，GET 支持 ETag/304；SSE 待接 VA Watch 对接。
- 订阅链路不再调用 VSM；VSM 仅负责“拉取上游 + 再发布 + 健康可视化 + 启停”。

### 4.1 CP API 契约

- POST `/api/subscriptions`：接受 `source_id|source_uri, stream_id, profile, model_id?`；生成 `cp_id`，调用 VA 订阅；`202+Location`；`Access-Control-Expose-Headers: Location,ETag`。
- GET `/api/subscriptions/{id}`：`200` 或 `304`（ETag 基于 timeline 版本）；data `{ id, phase, reason?, pipeline_key }`。
- DELETE `/api/subscriptions/{id}`：幂等 `202`，最佳努力 VA 取消。
- GET `/api/subscriptions/{id}/events`：SSE（由 VA Watch 推动，待对接）。
- GET `/api/system/info`：聚合 VA QueryRuntime 与 VSM 健康/源状态（可 1–2s 只读缓存），标注 `source=config|env|va|vsm`。
- 源管理：
  - GET `/api/sources`：优先 VSM `WatchState` 首帧，失败回退 `GetHealth`；返回 attach_id/source_uri/phase/fps 等。
  - POST `/api/sources:enable|disable`：调用 VSM `Update(options.enabled)` 启停源，返回 `202`。

### 4.2 gRPC 合同

- VA（需具备 Watch）
```
service AnalyzerControl {
  rpc Subscribe(SubscribeRequest) returns (SubscribeReply);
  rpc Get(GetRequest) returns (GetReply);
  rpc Cancel(CancelRequest) returns (CancelReply);
  rpc Watch(WatchRequest) returns (stream PhaseEvent);
  rpc QueryRuntime(Empty) returns (QueryRuntimeReply);
}
```
- VSM（启停/状态 + Restream 前提）
```
service SourceControl {
  rpc WatchState(WatchStateRequest) returns (stream WatchStateReply);
  rpc GetHealth(GetHealthRequest) returns (GetHealthReply);
  rpc Update(UpdateRequest) returns (UpdateReply); // options["enabled"]
  // 过渡：Attach/Detach 可保留一段时间以兼容旧流
  rpc Attach(AttachRequest) returns (AttachReply);
  rpc Detach(DetachRequest) returns (DetachReply);
}
```

## 5 配置与错误映射

- `restream.rtsp_base`：默认 `rtsp://127.0.0.1:8554/`，CP 将 `source_id` 映射为稳定端点。
- 错误与背压：ACL/参数错误→4xx；背压→429（含 Retry-After）；上游不可用→503；未知→500。

## 6 迁移与回滚

- 前端 baseURL 切至 CP；订阅切换为 `source_id`（CP 转译）；旧 attach 流保留灰度期后移除。
- VA Watch 可用后接入 SSE；若 Watch 未就绪，先提供 REST 最小闭环与 system.info/源管理。

## 7 验收

- 最小 API：POST 202+Location、GET ETag/304、DELETE 202。
- 源管理：/api/sources 列表与 enable/disable 生效；状态与指标可见。
- SSE：对接 VA Watch 后，phase 流事件稳定；整体无桥接、低耦合。
