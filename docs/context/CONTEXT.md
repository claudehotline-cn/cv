# 项目上下文（重建版）

本文档汇总当前对话与本次改动的关键上下文，覆盖代码结构、接口语义、可观测性、构建运行与测试事实证据，以及后续工作方向，供团队与 CI/CD 参考。

## 仓库与模块
- video-analyzer（VA）：核心后端。职责：RTSP 接入、预处理、推理、后处理、WHEP/HLS 输出、REST/SSE、Prometheus 指标、内嵌控制平面桥接。
- video-analyzer/src/control_plane_embedded（CP）：内嵌控制平面控制器（gRPC/REST），后续可独立化。
- video-source-manager（VSM）：RTSP 源管理（gRPC/REST）。
- web-frontend：Web 前端，用于预览流与叠加层。
- docs：设计/计划/示例/参考/需求/备忘录。
- tools：构建与运行脚本（Windows 首选 pwsh）。

## 本次结构性改动（大文件拆分）
目标：将 4000+ 行的 server/rest.cpp 按业务拆分，消除巨石文件带来的可维护性与编译时间问题。已完成：
- 新增按主题的实现文件（均在 video-analyzer/src/server/）：
  - rest_impl_core.cpp（Impl 构造/启动/DB 线程/保留通用内部实现）
  - rest_routes.cpp（路由装配）
  - rest_metrics.cpp（/metrics 与 metrics 配置）
  - rest_logging.cpp（日志配置与日志/事件 SSE）
  - rest_control.cpp（控制平面 REST：apply/apply_batch/hotswap/remove/status/drain 等）
  - rest_system.cpp（/api/system/info、/api/system/stats、图谱枚举等）
  - rest_models.cpp（模型/配置枚举）
  - rest_sources.cpp（sources 聚合 + watch + SSE）
  - rest_sessions.cpp（会话列表/长轮询）
  - rest_subscriptions.cpp（订阅创建/查询/删除，SSE 由 logging/sources 覆盖）
  - rest_db.cpp（数据库健康/清理/保留期状态）
  - rest_whep.cpp（WHEP 协商与可选 gRPC 转发）
- 新增头文件 rest_impl.hpp：仅保留声明与公用工具（HttpRequest/HttpResponse、SimpleHttpServer、JSON/ETag/错误回应等）。
- 调整 CMake 以纳入新源文件；构建通过。

## API 行为与本次修复
- /api/subscriptions（关键语义补全）
  - POST /api/subscriptions → 202 + Location 头（指向 /api/subscriptions/{id}），并通过 Access-Control-Expose-Headers 暴露 Location；响应体 { success, code, data }。
  - GET /api/subscriptions/{id} → 支持 ETag/If-None-Match：未变化返回 304；变化时 200 并携带 ETag（弱校验值基于 phase 与各阶段时间戳聚合）。
  - DELETE /api/subscriptions/{id} → 取消并返回 202，持久化状态（若启用 MySQL）。
- /metrics：基础指标可见（系统与全局指标），阶段直方图将在后续 M1/M2 中完善。
- 其余路由保持原有语义，现由 rest_routes.cpp 统一注册。

## 构建、运行与发布
- Windows（首选）：tools/build_va_with_vcvars.cmd，构建目录 video-analyzer/build-ninja。
- 运行 VA：build-ninja/bin/VideoAnalyzer.exe build-ninja/bin/config（Windows 选定配置子目录）。
- 验证监听：netstat -ano | find 8082；健康检查：GET http://127.0.0.1:8082/api/system/info。
- 注意：当重新链接失败（LNK1104）多因进程占用 exe，需先 Stop-Process VideoAnalyzer 再构建。

## 测试与证据
- 自动脚本（video-analyzer/test/scripts/）：
  - check_headers_cache.py：验证 202+Location、ETag/304、（可选）429+Retry-After。当前结果：通过（队列未饱和时 429 跳过警告属预期）。
  - check_metrics_exposure.py：验证基础指标曝光，当前结果：通过（阶段直方图缺失为 WARN，将在 M1/M2 完善）。
- 手工确认：/api/system/info 返回 engine/runtime/observability/subscriptions/database 快照正常。

## 可观测性与指标
- 系统：管线总数/运行数/FPS/传输包与字节。
- 零拷贝路径与全局计数：d2d_nv12_frames、cpu_fallback_skips、eagain_retry_count、overlay_* 等。
- 控制平面请求总数与耗时直方图：在 Impl 中聚合。
- 订阅队列与 in_progress 快照（SubscriptionManager）：后续将按阶段输出直方图与失败原因聚合。

## 近期完成的关键任务
1) 拆分巨石文件，恢复可维护性与编译速度；
2) 增补订阅接口的 HTTP 约定（Location、ETag/If-None-Match）；
3) 修复 Windows 构建链路中 exe 占用导致的链接失败；
4) 增加并运行后端校验脚本，CI 友好。

## 待办（高优先级）
- M1：WAL/Restart 扫描、Model/Codec Registry 预热、/api/system/info 暴露预热状态、/metrics 增补 failed(restart) 与 inflight 时长。
- M2：配额/ACL 策略、Grafana 大盘、压测与 24h soak、P95 与失败率达标。
- SSE/长连接健壮性：socket 泄漏、异常关闭与重试策略的监控与缓解。

## 术语
- ETag/If-None-Match：用于订阅轮询的缓存与 304 语义，降低 GET 风险与负载。
- WAL：重启后恢复 inflight 的持久化日志。
- WHEP：WebRTC HTTP Egress；可本地或经 gRPC 转发到其他 VA。
