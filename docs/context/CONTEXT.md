# 项目对话上下文（2025-10-18）

本文件汇总本轮对话与实现的关键事实，用于研发/联调/取证同步。

## 后端（VA：VideoAnalyzer）
- 控制面路由：POST /api/control/apply_pipeline、POST /api/control/apply_pipelines、POST /api/control/hotswap、POST /api/control/drain、DELETE /api/control/pipeline、GET /api/control/status（已联调）。
- Drain 可观测：
  - 执行器层探针：编码器回压（encoder_backpressure，基于 eagain_retry_count 10ms 窗口），节点自省：roi.batch（CPU/CUDA）截断（blocked_nodes=roi_batch.*，reason=roi_truncated）、model 近期推理失败（blocked_nodes=model，reason=infer_failed_recent）。
  - 控制面状态聚合：status.data.drain 输出 timeout_sec/elapsed_ms/ok/reason/blocked_nodes。
- /metrics 增强（Prometheus 0.0.4）：
  - 新增控制面指标：va_cp_requests_total{op,code}、va_cp_request_duration_seconds_{bucket,sum,count}（op 覆盖 apply/apply_batch/hotswap/drain/remove）。
  - 既有 DB 指标：va_db_pool_*、va_db_writer_queue_{events,logs}、va_db_retention_* 持续输出。
- 数据面与稳定性（存量）：REST DB-only（sessions/events/logs）、分页/时间窗/过滤、连接/收发超时、SSE 去锁化、CORS；/api/db/retention/status；/metrics 文本/registry 分支。

## 源管理（VSM）
- REST 路由：/api/source/list/update/add/delete、/api/source/watch（长轮询）、/api/source/watch_sse（SSE）。
- 编排路由（新增）：
  - POST /api/orch/attach_apply（Attach 源 + 调 VA ApplyPipeline）。
  - POST /api/orch/detach_remove（Detach 源 + 调 VA RemovePipeline）。
  - GET /api/orch/health（VSM 源汇总 + 透传 VA /api/system/info）。
- HTTP 客户端（内置 socket）：补 Host:port、SO_SNDTIMEO/RCVTIMEO，DELETE 超时 8s + 重试 2 次；POST 8s + 重试 1 次。
- JSON 校验：id（^[A-Za-z0-9_-]{1,64}$）与 RTSP 前缀校验（/api/source/add&update）。
- /metrics：vsm_rest_requests_total{path,code} 与 vsm_rest_request_duration_seconds*；SSE 指标 vsm_sse_connections/vsm_sse_rejects_total/vsm_sse_max_connections。

## 前端（web-front）
- 新增编排页面：/orchestration
  - 表单：Source ID、RTSP URI、Pipeline 名称、YAML 路径；操作：Attach+Apply、Detach+Remove。
  - 健康卡片：聚合 VSM total/running 与 VA system/info 摘要（Engine/DB/Models/Pipelines 等）。
  - 入口：侧边栏 Orchestration；路由已接入（部分预览环境需全量重启预览或强刷缓存）。
- 既有可观测：Metrics/Logs/Events/Sessions DB 模式；Sessions 默认 30 天窗口；错误显式展示。

## 构建/运行
- VA：tools/build_with_vcvars.cmd（必要时先停 EXE 以避免 LNK1104），运行：build-ninja/bin/VideoAnalyzer.exe bin/config。
- VSM：cmake -S . -B build -DUSE_GRPC=OFF && cmake --build build，运行：build/bin/Debug/VideoSourceManager.exe（REST 7071、/metrics 9101）。
- 前端：npm run build；预览：tools/win/restart_frontend_preview.ps1（默认 4173）；开发：npm run dev（默认 5173）。

## 取证与脚本
- VA 控制面：docs/memo/assets/2025-10-18/cp_hotswap_status_check.json、cp_status_hs_demo_2_after_apply.json、metrics_cp_excerpt.txt。
- VSM 健康：docs/memo/assets/2025-10-18/vsm_orch_health.json、vsm_metrics_full.txt、vsm_metrics_excerpt.txt。
- 前端编排取证（简要）：docs/memo/assets/2025-10-18/front_orch_eval.json（health=OK，路由需强刷）。
- 辅助脚本：tools/win/restart_backend.ps1、restart_frontend_preview.ps1、probe_api.ps1。

## 已知事项与下一步
- 预览路由偶发 404：已build+重启，需浏览器强刷；或改用 dev 模式。
- 编码器回压为全局启发式：后续改为 pipeline 级（TrackManager 导出 zc.eagain_retry_count）。
- 节点自省覆盖面：可扩展 overlay/preproc/join 等常见节点的队列/截断/丢帧信号。
- 前端自动化：待 Orchestration 路由稳定后，补完整 Playwright 流程（填表→Attach+Apply→Health→Detach+Remove）并固化 JSON 取证。
