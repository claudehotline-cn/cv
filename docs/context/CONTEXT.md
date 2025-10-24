# 项目上下文（重建版｜2025-10-24）

本文汇总当前对话期间完成的关键变更、接口语义、可观测性、构建运行与测试证据，以及 M1（WAL 与预热）推进状态，供团队协作与 CI/CD 参考。

## 仓库与模块
- video-analyzer（VA）：核心后端。RTSP 接入、预处理/推理/后处理、WHEP/HLS 输出、REST/SSE、Prometheus 指标。
- video-analyzer/src/control_plane_embedded（CP）：内嵌控制平面路由与控制器（gRPC/REST）。
- video-source-manager（VSM）：RTSP 源管理（gRPC/REST）。
- web-frontend：Web 前端（预览、叠加层与观测）。
- docs：设计、计划、参考、需求、备忘录；tools：构建与运行脚本（Windows 优先 pwsh）。

## 大文件拆分（已完成）
- 将 4000+ 行的 server/rest.cpp 按业务主题拆分为：
  - rest_impl_core.cpp（Impl 构造/启动、DB 线程、通用内部逻辑）
  - rest_routes.cpp（路由注册）
  - rest_metrics.cpp（/metrics 与指标配置）
  - rest_logging.cpp（日志配置与日志/事件 SSE）
  - rest_control.cpp（控制面 REST：apply/apply_batch/hotswap/remove/status/drain）
  - rest_system.cpp（/api/system/info、/api/system/stats、图谱枚举）
  - 以及 rest_models.cpp、rest_sources.cpp、rest_sessions.cpp、rest_subscriptions.cpp、rest_db.cpp、rest_whep.cpp
- 新增 rest_impl.hpp：集中声明与通用工具（HttpRequest/HttpResponse、SimpleHttpServer、错误与 JSON 工具）。
- CMake 已纳入新源；构建通过。

## 接口语义修复（M0）
- /api/subscriptions
  - POST → 202 + Location（指向 /api/subscriptions/{id}），并通过 Access-Control-Expose-Headers 暴露 Location。
  - GET /{id} → 支持 ETag/If-None-Match：未变化返回 304；变化 200 并携带弱 ETag（基于 phase 与时间线哈希）。
  - DELETE /{id} → 202；若启用 DB，持久化完成态。
- 其余 API 维持原语义，由 rest_routes.cpp 统一注册。

## 可观测性与指标（M0→M1）
- 基线（/metrics）：系统（管线/FPS/传输）、全局（零拷贝/编码器重试）、控制面（总数+耗时直方图）、订阅（队列/状态/完成态/时长直方图/失败原因）。
- 新增（M1）：va_wal_failed_restart_total（上次重启前 inflight 的近似计数）。

## WAL 集成（M1｜已接入最小闭环）
- 环境变量：VA_WAL_SUBSCRIPTIONS=1（启用）、VA_WAL_MAX_BYTES、VA_WAL_MAX_FILES、VA_WAL_TTL_SECONDS（滚动/保留）。
- 文件：logs/subscriptions.wal（JSON 行）；事件：enqueue/ready/failed/cancelled/restart。
- 生命周期：订阅入队与完成态写 WAL。
- 启动：wal::init() → mark_restart() → scanInflightBeforeLastRestart()。
- /api/system/info 暴露 wal: { enabled, failed_restart }。

## 模型注册表预热（M1｜已接入最小闭环）
- 环境变量：VA_MODEL_REGISTRY_ENABLED、VA_MODEL_REGISTRY_CAP、VA_MODEL_IDLE_TTL_SEC、VA_MODEL_PREHEAT_ENABLED、VA_MODEL_PREHEAT_CONCURRENCY、VA_MODEL_PREHEAT_LIST。
- 启动：加载模型清单 → 解析预热配置 → 后台并发预热（best‑effort）。
- /api/system/info 暴露 registry.preheat: { enabled, concurrency, list, status: idle|running|done, warmed }。

## 构建与运行
- Windows：& tools/build_va_with_vcvars.cmd
  - 生成目录：video-analyzer/build-ninja
  - 运行：build-ninja/bin/VideoAnalyzer.exe build-ninja/bin/config
  - 常见：LNK1104（exe 被占用）→ 先 Stop-Process VideoAnalyzer 再构建。
- 健康检查：GET http://127.0.0.1:8082/api/system/info（code=OK）。

## 测试与证据
- 脚本：
  - check_headers_cache.py：验证 202+Location、ETag/304；队列未饱和时 429 跳过为 WARN → 通过。
  - check_metrics_exposure.py：基础指标曝光 → 通过（阶段直方图缺失为可接受 WARN）。
- 手工：/api/system/info 新增 registry.preheat 与 wal 字段；/metrics 新增 va_wal_failed_restart_total；8082 监听正常。

## 待办（M1 继续）
- 管理接口：/api/admin/wal/summary、/api/admin/wal/tail?n=200（读取证）。
- 指标：订阅分阶段直方图与 WAL 维度标签；预热耗时与错误计数。
- 脚本：WAL/预热校验脚本纳入 CI；文档补充 app.yaml 示例。

## 进展追加（2025-10-24）
- 新增管理接口（只读取证）：
  - GET `/api/admin/wal/summary` → `{ enabled, failed_restart }`。
  - GET `/api/admin/wal/tail?n=200` → `{ count, items[] }`（WAL 活动文件尾部）。
- 指标补充：
  - 订阅分阶段耗时直方图（opening_rtsp/loading_model/starting_pipeline）。
  - 预热相关：`va_model_preheat_enabled`、`va_model_preheat_concurrency`、`va_model_preheat_warmed_total`、`va_model_preheat_duration_seconds{le=...}`、`va_model_preheat_failed_total`。
  - `/metrics` 中 WAL 暴露：`va_wal_failed_restart_total`（已存在）。
- 启动流程补强：
  - 进程启动时 `wal::init()` → `mark_restart()` → `scanInflightBeforeLastRestart()`。
  - ModelRegistry：从环境装配、采集模型清单、触发最小预热（并发可控）。
- 测试新增：
  - `test/scripts/check_admin_wal_endpoints.py`：管理接口基本校验（通过）。
  - `test/scripts/check_preheat_status.py`：设置环境变量后校验 `/api/system/info.registry.preheat` 字段（通过）。
  - `test/scripts/check_wal_scan.py`：启用 WAL 后制造一次订阅与快速重启，检查 `failed_restart` 非负且启用（通过）。
