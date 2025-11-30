# CONTEXT（2025-11-26，controlplane Spring 重写与 VA/VSM 集成现状）

本文件汇总当前围绕 **controlplane Spring Boot 重写（cp-spring）** 的关键实现、配置与测试结论，作为后续路线图与排障的统一上下文。

---

## 一、总体目标与架构轮廓

- 将现有 C++ ControlPlane 的 HTTP/SSE 行为，逐步重写为独立的 `controlplane-spring` 子项目：
  - 技术栈：Spring Boot 3.1.x + Java 21 + Maven。
  - gRPC 客户端：`VideoAnalyzerClient`（VA）、`VideoSourceManagerClient`（VSM）。
  - 数据访问：MyBatis-Plus + MySQL（复用 `cv_cp`）。
  - 部署：Docker 多阶段构建 `cv/cp-spring` 镜像，通过 `docker/compose` 与 VA/VSM/MySQL 在同一网络中运行。
- 兼容性目标：
  - 与现有 C++ CP 在 HTTP 路由、JSON 结构与错误语义上尽量保持一致（特别是 `controlplane/test/scripts` 下的 Python 回归脚本）。
  - 提前预留 SSE 与观测能力（Micrometer + Prometheus）。

---

## 二、cp-spring 项目实现现状

### 2.1 基础骨架

- `ControlPlaneApplication`：主启动类，启用 `AppProperties` 配置绑定。
- `AppProperties`：
  - `cp.va` / `cp.vsm`：gRPC 地址、TLS 证书路径、超时/重试参数。
  - `cp.restream` / `cp.sfu`：RTSP/WHEP 基础配置。
  - `cp.security` / `cp.db`：安全与数据库连接信息。
- Actuator：
  - 已开放 `/actuator/health` `/actuator/info` `/actuator/metrics` `/actuator/prometheus`。

### 2.2 VA/VSM gRPC 客户端

- `GrpcChannelConfig`：
  - VA/VSM 通道使用 Netty + TLS/mTLS，优先从 `cp.*.tls` 读取 CA 与 client cert/key。
  - 通过 `.overrideAuthority("localhost")` 对齐开发证书 SAN。
  - TLS 失败时回退 plaintext 模式。
- `VideoAnalyzerClient`：
  - 封装 VA 核心 RPC：`SubscribePipeline/UnsubscribePipeline/ApplyPipeline/Drain/ListPipelines/QueryRuntime/RemovePipeline/HotSwapModel/SetEngine`。
  - 超时从 `cp.va.timeout-ms` 注入；所有方法使用 `@CircuitBreaker(name="va")`。
- `VideoSourceManagerClient`：
  - 封装 VSM RPC：`Attach/Detach/Update(GetHealth)/WatchState`。
  - unary 调用从 `cp.vsm.timeout-ms` 读取 deadline（默认 500ms，可按环境调大），避免在 VSM 不可用时拖垮 HTTP 请求，同时兼顾在真实 VA/VSM 环境下的稳定性。

### 2.3 HTTP/API 层

- 订阅与系统信息：
  - `/api/subscriptions`（POST/GET/DELETE）：与 Python 脚本对齐，支持 query + JSON 混合传参，ETag/304，以及 demo SSE `/api/subscriptions/{id}/events`。
  - `/api/system/info`：返回 `restream.rtsp_base`，经 Caffeine 缓存（TTL 5s）。
- 源管理：
  - `/api/sources:attach|:detach|:enable|:disable`：
    - 直接调用 VSM gRPC Attach/Detach/Update。
    - 源列表 `/api/sources` 通过 VSM `GetHealth` 构建，不再维护本地 `SourceItem` 状态。
  - SSE：`/api/sources/watch_sse` 使用 `WatchState` 流输出 `event: state`，满足 `check_cp_sources_watch_sse.py`。
- 控制与 VA Runtime：
  - `/api/control/apply_pipeline/remove_pipeline/hotswap/drain/set_engine/pipelines` 通过 `ControlService` 调用 VA gRPC，实现管线控制与引擎配置。
  - `/api/va/runtime` 返回 VA 当前 provider/gpu_active/io_binding/device_binding。
- 全局异常处理：
  - `GlobalExceptionHandler` 将 `StatusRuntimeException` 映射为 HTTP 400/404/409/503/500，并设置 `code/msg`。

---

## 三、VSM 行为与当前限制

- VSM 服务：
  - Docker 镜像 `cv/vsm:latest`，在 7070 提供 gRPC SourceControl、7071 提供 HTTP health。
  - 内置 `SourceController` 使用 `FfmpegRtspReader`（在无 OpenCV 的情况下为 stub，不真正拉 RTSP）。
  - gRPC 服务在 `GrpcServer` 中通过 TLS 启动，CA 与 server cert 从 `video-source-manager/config/certs` 提供。
- 当前观察：
  - cp-spring → VSM gRPC Attach 在 500ms 内经常返回 `DEADLINE_EXCEEDED`，导致 `/api/sources:attach` 返回 500，Python 脚本判断为 `backend not available (VSM)` 并 SKIP；
  - 源列表 `/api/sources` 已改为依赖 VSM `GetHealth`，不存在本地 SourceItem 偏差，但前提是 Attach 调用至少成功一次。

---

## 四、测试现状（controlplane/test/scripts）

- 已稳定 PASS：
  - `check_cp_system_info.py`：验证 `restream.rtsp_base`。
  - `check_cp_json_negative.py`：多处 JSON 负向用例（subscriptions/sources/control/drain）。
  - `check_cp_min_api_once.py`：已将 profile 从 `p1` 调整为 VA 存在的 `det_720p`，在 cp-spring + VA 配置下 PASS。
  - `check_cp_sse_placeholder.py`：`/api/subscriptions/demo-id/events` 返回 501。
  - `check_cp_sse_watch.py`：设 `CP_TEST_PROFILE=det_720p` 时，SSE 事件流 PASS。
  - `check_cp_sources_watch_sse.py`：`/api/sources/watch_sse` SSE STATS PASS。
- 受 VSM 状态影响而 SKIP：
  - `check_cp_sources_attach_detach.py`、`check_cp_sources_enable_disable.py`：在 VSM gRPC Attach/Update 报错或超时时，按约定打印 `SKIP: backend not available (VSM)`。

---

## 五、后续工作方向（与 ROADMAP 对应的要点）

1. **Phase E（TE3/TE4）**：补全缓存层行为，系统性验证冷启动/异常场景下 DB + 缓存的一致性。
2. **Phase F（TF1–TF4）**：接入 Spring Security、Micrometer 指标与 Prometheus/Grafana 仪表盘，增加审计日志。
3. **Phase G（TG1–TG4）**：扩充单元/集成测试，设计 C++ CP 与 Spring CP 并行灰度方案与回滚预案。

以上内容作为 cp-spring 与 VA/VSM 集成的当前事实基础，ROADMAP 将在此基础上拆解里程碑与阶段计划。 
