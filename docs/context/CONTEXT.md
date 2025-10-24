# 项目上下文（2025-10-24 刷新）

本文整合当前对话的关键结论：代码/模块拆分、REST 语义强化、WAL 与预热（M1）、配额/ACL 灰度（M2）推进、测试方式与运行环境要求，作为后续协作与验证的统一上下文。

## 仓库与模块
- `video-analyzer`（VA）：核心后端，RTSP 接入、预处理/推理/后处理、REST/SSE、Prometheus、WHEP/HLS。
- `video-analyzer/src/control_plane_embedded`（CP）：控制平面，前端仅与 CP 交互；CP/VA/VSM 之间 gRPC。
- `video-source-manager`（VSM）：视频源管理（gRPC/REST/metrics）。VSM 的 gRPC 为必选能力。
- `web-front`：管理/预览/Admin 面板。
- `docs`：设计/计划/参考/需求/备忘；`tools`：构建运行与测试脚本。

## 工作约束与流程
- 统一使用中文、Windows pwsh；修改用 `apply_patch`；构建通过后必须测试；每次任务结束在 `docs/memo` 追加当日记录。
- 前端测试遵循“最小充分取证”，使用 Playwright MCP 或 Chrome DevTools MCP（截图仅保存路径，评估仅返回结构化 JSON）。

## REST 与服务拆分（M0 已完成）
- 将 4000+ 行 `src/server/rest.cpp` 按业务拆分为：`rest_impl_core.cpp`、`rest_routes.cpp`、`rest_metrics.cpp`、`rest_logging.cpp`、`rest_control.cpp`、`rest_system.cpp`、`rest_models.cpp`、`rest_sources.cpp`、`rest_sessions.cpp`、`rest_subscriptions.cpp`、`rest_db.cpp`、`rest_whep.cpp`，并更新 CMake。
- 语义加固：
  - `POST /api/subscriptions` 返回 `202 + Location`（并通过 `Access-Control-Expose-Headers` 暴露）。
  - `GET /api/subscriptions/{id}` 支持 `ETag/If-None-Match` 与 `304`（弱 ETag 基于 phase+timeline）。
  - 取消与 reason 归一：各路径均调用 `recordCompletion`，统一 canonical reason，填充 `ts_cancelled/ts_failed`。
- 系统信息：暴露 `open_rtsp_slots/start_pipeline_slots/load_model_slots`，值来源 config/env，回显在 `/api/system/info`。

## 可观测性与指标
- 基础指标：请求/错误/阶段耗时直方图、失败原因分布、特性开关（如 `va_feature_enabled{feature="wal"}`）。
- 订阅阶段指标：`opening_rtsp/loading_model/starting_pipeline` 分阶段直方图。
- 配额指标（M2）：`va_quota_dropped_total`、`va_quota_would_drop_total`、`va_quota_enforce_percent` 等。

## WAL 与预热（M1 最小闭环已接线）
- WAL：`wal::init()` → `mark_restart()` → `scanInflightBeforeLastRestart()`；订阅 enqueue/终止事件以 JSONL 形式写入 `logs/subscriptions.wal`（支持滚动/TTL，env 可配）。
- 指标：`va_wal_failed_restart_total`；特性开关指标暴露。
- Admin：`GET /api/admin/wal/summary`、`GET /api/admin/wal/tail?n=200`。
- 预热：通过 `VA_MODEL_PREHEAT_ENABLED/CONCURRENCY/LIST` 启用；后台执行，`/api/system/info` 暴露 `registry.preheat { enabled, concurrency, list, status, warmed }` 与相关指标。

## 配额/ACL 灰度（M2 启动）
- 策略：`observe_only`、`enforce_percent`、`exempt_keys`、`key_overrides`，并支持按 scheme/profile 定义。
- 指标：丢弃与“将丢弃”计数、特性开关、多面板观测（Grafana 建议面板已扩展）。

## 运行与测试
- 构建（Windows）：`& tools/build_va_with_vcvars.cmd`；运行：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe video-analyzer/build-ninja/bin/config`。
- 端口与依赖：VA REST 8082；VSM gRPC 7070 / REST 7071；数据库 MySQL at `127.0.0.1:13306`；测试 RTSP `rtsp://127.0.0.1:8554/camera_01`。
- 脚本：
  - `tools/run_ci_smoke.ps1`：headers/ETag、metrics、WAL、预热等冒烟。
  - `tools/run_rtsp_e2e.ps1`：编排 VSM/VA、接入 RTSP、检查 `/system/info`、SSE 取消、metrics、轻量 soak；支持 `-DurationMin`、`-HttpTimeout`。
  - Python 测试位于 `video-analyzer/test/scripts/`（如 `check_headers_cache.py`、`check_metrics_exposure.py`、`check_cancel_sse_trace.py`、`check_system_info_subs.py`）。

## 待办与注意
- Soak 误差：短窗/并发下偶发连接拒绝，需调大 `DurationMin`（≥0.5）与 `HttpTimeout`（≥15s），或设置误差阈值（err/ok<1%）。
- 在 `subscription_manager.cpp` 再次核对所有失败/取消分支均调用 `recordCompletion`；完善 reason 归一映射以降低 `unknown` 占比。
- 更新 `app.yaml` 示例以涵盖 WAL/预热/配额灰度字段；Grafana 面板补充配额相关展示。

## 依赖矩阵（摘要）
- 内部：VA ⇄ VSM（gRPC/REST）；CP ⇄ VA/VSM（gRPC）；前端 ⇄ CP（HTTP）。
- 外部：MySQL(13306)、RTSP 服务、可选 CUDA/NV 编解码、Prometheus/Grafana。

