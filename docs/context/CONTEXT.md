# 项目上下文（自动生成 · 订阅与播放全链路）

本文件汇总当前对话期间已实现与在研的关键信息，覆盖后端（VA/CP/VSM）、前端（web-front）、测试与运维观测。

## 架构与模块
- VA（video-analyzer）：RTSP 接入、预处理/推理/后处理、WHEP/WebRTC/HLS 输出；异步订阅与 SSE 事件流的服务端实现与指标出口。
- CP（control_plane_embedded，内嵌于 VA）：提供管线编排与控制面 API（后续可独立）。
- VSM（video-source-manager）：RTSP 源管理（gRPC 7070 / REST 7071）。
- 前端（web-front）：统一走 createSubscription + SSE 路径，分析页播放（WHEP），观测页（Observability）与会话视图（Sessions）。

## 关键接口（现状）
- 订阅 REST：
  - POST `/api/subscriptions?use_existing=1`（或头 `X-Subscription-Use-Existing: 1`）→ 202 + { id, phase=pending }；幂等复用相同 `stream_id:profile`。
  - GET `/api/subscriptions/:id` → { phase, reason, pipeline_key, whep_url, created_at_ms }；终态时兜底持久化会话。
  - DELETE `/api/subscriptions/:id` → 取消，兜底持久化会话。
- 订阅事件 SSE：GET `/api/subscriptions/:id/events`
  - 事件 `phase`：pending → preparing → opening_rtsp → loading_model → starting_pipeline → ready/failed/cancelled；10s keep-alive。
- 源：GET `/api/sources`；SSE `GET /api/sources/watch_sse`（已启用）。
- 系统信息：GET `/api/system/info` → `subscriptions.{heavy_slots,model_slots,rtsp_slots,max_queue,ttl_seconds}` 与 SFU/WHEP 基址等。
- 播放：WHEP `/whep` 系列（前端 WhepPlayer 与后端 WhepSessionManager）。

## 并发/限流/队列（现状）
- `heavy_slots`（兼容项）、分阶段信号量：
  - `model_slots`：`loading_model` 并发（默认 2）。
  - `rtsp_slots`：`starting_pipeline`/打开 RTSP 并发（默认 4）。
- 队列上限：`max_queue`（默认 1024），满则 POST /api/subscriptions 返回 429 queue_full。
- TTL 清理：`ttl_seconds`（默认 900s），终态订阅逾时由清理线程回收（内存状态）。
- 配置方式：环境变量（VA_SUBSCRIPTION_MODEL_SLOTS / RTSP_SLOTS / HEAVY_SLOTS / MAX_QUEUE / TTL_SEC），后续接入 YAML（规划中）。

## 指标与观测（现状）
- Prometheus 文本 `/metrics`：
  - `va_subscriptions_queue_length`、`va_subscriptions_in_progress`、`va_subscriptions_states{phase}`。
  - `va_subscriptions_completed_total{result=ready|failed|cancelled}`。
  - `va_subscription_duration_seconds[_bucket/_sum/_count]`（总时长直方图）。
  - `va_subscriptions_failed_by_reason_total{reason}`（失败原因标准化：open_rtsp_failed/_timeout、load_model_failed/_timeout、subscribe_failed、unknown）。
- Grafana：已提供示例仪表盘与告警规则（docs/observability/grafana/*）。
- 前端 Observability：
  - System Info 卡片显示 WHEP Base 与 `heavy_slots/model_slots/rtsp_slots/max_queue/ttl_seconds`。
  - Sessions 页面展示最近会话（已对接 DB/兜底快照）。

## 前端（现状）
- 统一路径：Sources/List、Pipelines/AnalysisPanel、Stores/analysis.ts 走 `startAnalysis()/stopAnalysis()` → `createSubscription + SSE`，ready 后设置 WHEP URL 与播放。
- 进度条：仅 SSE 就绪后 `analyzing=true`；错误终态集中展示；“取消”按钮走 `stopAnalysis()`。
- 刷新稳定性：
  - 前端 beforeunload 使用 `sendBeacon`/`fetch keepalive` 发送 WHEP DELETE；
  - 后端 PeerConnection Closed/Failed 自动 `deleteSession`，避免刷新崩溃与悬挂会话。
- 源监听：优先 VA `/api/sources/watch_sse`，失败回退 VSM SSE，再回退长轮询。

## 测试与E2E（现状）
- 数据源：`rtsp://127.0.0.1:8554/camera_01`（mediamtx/ffmpeg）。
- 用例（Playwright）已手动执行：Start→Ready→取消、sources→analysis 路由、错误源行为；计划脚本化入仓并接入 CI。

## 已知/已修复
- 刷新播放崩溃：已通过 WHEP 会话优雅关闭与后端自清理修复。
- 旧控制平面订阅接口：前端已停用，后端保留（后续按开关 410 逐步移除）。

## 待办（高优先）
- 配置接入 YAML（ttl/slots/queue 等），`/api/system/info` 回显来源（env/config）。
- 订阅时间线：GET include=timeline 与 SSE Last-Event-ID；阶段化耗时直方图；原因维度告警面板。
- E2E 用例落档与 CI；并发与长稳压测（N=50/100、24h）。
