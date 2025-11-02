# VA → CP REST 迁移指南

本指南梳理将 Video Analyzer（VA）对外 REST 职责上收至 Controlplane（CP）的变更，帮助调用方与开发者顺利迁移。

## 目标与边界
- 对外 REST/SSE 统一由 CP 提供：订阅、源管理、系统信息、编排（attach_apply/hotswap/drain/delete/status）。
- VA 仅保留：媒体输出（WHEP/WHIP 等）与自身 `/metrics`。
- gRPC 拓扑不变：CP 作为 gRPC 客户端访问 VA/VSM；全链路 TLS/mTLS 可选。

## 路由映射（主要）
- 订阅与事件：
  - 旧（VA）：`/api/subscriptions/*`、`/api/subscriptions/{id}/events`
  - 新（CP）：`/api/subscriptions/*`、`/api/subscriptions/{id}/events`
- 源管理与监控：
  - 旧（VA）：`/api/sources`、`/api/sources/watch_sse`
  - 新（CP）：`/api/sources`、`/api/sources/watch_sse`
- 编排控制：
  - 旧（VA）：`/api/control/*`、`/api/orch/*`
  - 新（CP）：`/api/control/*`、`/api/orch/*`
- 系统信息与观测：
  - 旧（VA）：`/api/system/*`、`/metrics`
  - 新（CP）：`/api/system/*`、`/metrics`（VA 自身 `/metrics` 仍保留，以区分组件指标）
- 媒体输出：
  - VA 保留：`/whep`、`/whep/sessions/:sid`（CP 不代理媒体通路）。

## 版本与兼容
- 自本次迁移起，VA 的公共 REST 路由已禁用（编译开关 `VA_DISABLE_HTTP_PUBLIC=ON`）。
- 前端 `.env` 默认指向 CP：`VITE_API_BASE=http://127.0.0.1:18080`。
- 若需临时回滚，可关闭编译开关恢复 VA 路由（不建议在生产使用）。
 - 可选“置灰”占位（410 Gone）：启用 `-DVA_REST_DEPRECATED_410=ON` 且 `VA_DISABLE_HTTP_PUBLIC=ON` 时，VA 会为已迁移的旧 REST 路由返回 410，并提示迁移至 Controlplane（不再提供真实功能）。

## TLS/mTLS 与一键化
- 一键启动（TLS）：`pwsh tools/start_stack_tls.ps1 -KillExisting`
- mTLS 连通性：`tools/test_mtls_connectivity.ps1`（正向）、`tools/test_mtls_negative.ps1`（负向）
- 证书路径：`controlplane/config/certs/`（脚本已在启动前校验 CA/Cert/Key 存在）

## 验收与回归
- Smoke（TLS）：`tools/run_cp_smoke.ps1 -BaseUrl http://127.0.0.1:18080 -CfgDir controlplane/config`
  - 覆盖：控制正/负、编排正/负（默认纳入负用例）、SSE 并发、指标与审计断言
- 指标 method 维度验证：`video-analyzer/test/scripts/check_cp_backend_errors_method.ps1`

## 注意事项
- 不要在 C++ 项目中引用 Anaconda 库（Python 允许）。
- Windows 构建前先停止运行中的进程，避免链接阶段文件锁（LNK1104）。
- 禁止随意清理构建目录。
