# CONTEXT（2025-10-25 更新）

本文汇总当前对话的关键结论、系统现状与测试规约，便于协作与追踪。

## 仓库与模块
- `video-analyzer`（VA）：核心后端，包含 RTSP 接入、预处理/推理/后处理、REST/SSE、Prometheus、WHEP/HLS。
- `video-analyzer/src/control_plane_embedded`（CP）：内嵌控制平面，前端只与 CP 交互；CP/VA/VSM 通过 gRPC。
- `video-source-manager`（VSM）：管理 RTSP 源，提供 gRPC/REST/metrics。
- `web-front`：前端 UI（预览、Admin）。`docs/` 为设计/计划/参考与测试指南；`tools/` 为构建与测试脚本。

## 工作方式与约束
- 统一使用 Windows `pwsh`；通过 `apply_patch` 修改代码；每日将进展追加到 `docs/memo`。
- 前端测试遵循最小充分取证（Playwright MCP/Chrome DevTools MCP）；后端测试优先 Python 脚本与 pwsh 编排。

## 现状快照
1) REST 拆分（M0 完成）
   - 4000+ 行 `rest.cpp` 拆为若干按域文件并更新 CMake；语义加固：
     - `POST /api/subscriptions` 返回 `202+Location`（并暴露 `Access-Control-Expose-Headers`）。
     - `GET /api/subscriptions/{id}` 支持 `ETag/If-None-Match` 命中 `304`（弱 ETag 来源于 phase+timeline）。
     - 取消与失败 reason 统一映射，补齐 `ts_failed/ts_cancelled`。
2) LRO（通用长任务库，编译库形态）
   - `lro/` 提供 `Runner/Operation/StateStore/Executors/Notifier/Admission` 等通用接口；不含 VA 业务常量。
   - VA 订阅 POST/GET/DELETE/SSE 已切换到 Runner；/metrics 与 /system/info 使用 Runner 快照。
3) WAL 与预热（M1 完成最小闭环）
   - WAL 记录订阅 enqueue 与终态事件（JSONL，滚动与 TTL）；重启扫描统计 `failed_restart`；
   - `/admin/wal/summary`、`/admin/wal/tail` 管理只读端点；`/metrics` 暴露 `va_wal_failed_restart_total` 与 feature 开关。
   - 模型预热（列表/并发）与缓存指标已接入；`/system/info` 回显 `registry.preheat/cache` 状态。
4) 配额/ACL（M2 进行中）
   - 支持 observe_only/enforce_percent、exempt_keys、per-key overrides；动态 Retry-After 基于队列与槽位估算；
   - 暴露 `va_quota_dropped_total`、`va_quota_would_drop_total`、`va_quota_enforce_percent` 等指标。

## 指标与系统信息
- 订阅：`va_subscriptions_queue_length`、`va_subscriptions_in_progress`、`va_subscriptions_states{phase}`、完成总数与时长直方图；
- 预热/缓存：`va_model_preheat_*` 与 `va_model_cache_*`；
- SSE：连接与重连计数；Codec：decoder/encoder build/hit；WAL：`va_wal_failed_restart_total`；
- `/api/system/info` 回显 engine/options、subscriptions（slots/queue/states/source）、registry.preheat/cache、数据库与运行态快照。

## 构建与运行
- Windows：`& tools/build_va_with_vcvars.cmd`；运行：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe video-analyzer/build-ninja/bin/config`。
- 注意需先停止已运行的 `VideoAnalyzer.exe`，否则链接会失败（LNK1104）。

## 测试规约
- 位置：`video-analyzer/test/scripts`；常用：
  - 最小 API：`check_min_api_once.py`（POST→GET→DELETE+SSE）。
  - WAL：`check_admin_wal_tail.py`、`check_wal_scan.py`；
  - 预热/缓存：`check_preheat_status.py`、`check_model_cache_info.py`；
  - 配额/ACL：`check_quota_*`、`check_acl_profile_scheme.py`；
  - 指标：`check_metrics_exposure.py`、`check_metrics_hist_and_reasons.py`；
  - SSE：`check_sse_metrics.py`。

## 待办焦点（当前）
- 在 metrics registry 分支补齐 `va_subscriptions_in_progress`（已完成）。
- 将 `check_min_api_once.py` 集成进 `tools/run_ci_smoke.ps1`（已完成）。
- 在 `video-analyzer/CMakeLists.txt` 链接 `lro_runtime`（已完成）。

