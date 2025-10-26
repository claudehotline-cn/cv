# 项目上下文（最新）

## 架构与通信
- 组件：Controlplane（CP，HTTP+gRPC 中枢）、Video Analyzer（VA，推理与媒体）、Video Source Manager（VSM，源管理）、web-front（前端）。
- 通信：前端只连 CP（REST/SSE）；CP 通过 gRPC（TLS/mTLS）调用 VA/VSM；媒体（WHEP）由前端直连 VA（不经 CP 代理）。

## 关键改动与现状
1) TLS/mTLS 全链路
- VA/VSM gRPC 服务器支持 TLS（VA_TLS_*/VSM_TLS_* 环境变量）；CP 客户端凭据从 `controlplane/config/app.yaml` 读取。
- 脚本：`tools/start_stack_tls.ps1`（一键启动）/`tools/stop_stack.ps1`；mTLS 连通性：`tools/test_mtls_connectivity.ps1`、`tools/test_mtls_negative.ps1`。

2) 编排能力（CP 负责）
- 正向流程（attach_apply → status → drain → delete）与负路径（无效 spec/图）已纳入 `tools/run_cp_smoke.ps1`，默认执行负用例。
- 独立正向用例：`controlplane/test/scripts/smoke_orch_positive_flow.ps1`。

3) 指标与告警
- 新增 `cp_backend_errors_total{service,method,code}`，并在 smoke 中验证 method 维度增量（触发一次 VA ApplyPipeline 失败后断言增量）。
- Grafana/Prometheus：面板与告警聚合口径统一为按 (service,method,code) 维度统计；规则已更新。

4) VA REST 迁移与收口
- 默认禁用 VA 公共 REST：`VA_DISABLE_HTTP_PUBLIC=ON`，仅保留 `/metrics` 与 WHEP `/whep*`。
- 可选“置灰”开关：`VA_REST_DEPRECATED_410=ON` 时，旧 REST 路由返回 410 Gone（引导迁移至 CP）。
- 已删除/禁用的 VA REST：subscriptions/sources/system/control/orch/admin 等；仅保留排障必要实现。

5) 前端联调（分析页）
- 修复 dev 代理：`/whep` → VA:8082。
- 预检兼容：CP 无 `/api/preflight`，前端在非 mock 环境直接 ok:true。
- 订阅参数补全：创建订阅时在查询串附带 `stream_id/profile/source_uri` 或 `source_id`，CP 侧可据此回填；`.env` 新增 `VITE_DEFAULT_SOURCE_ID=camera_01` 用于兜底。
- 取证方式：使用 Chrome DevTools MCP 抓取 /api 与 /whep 关键请求和页面截图。

6) 稳定性与 CI
- SSE Soak：2 分钟基准（`tools/run_cp_sse_soak_tls.ps1`），日志归档于 `logs/soak_cp_sse_watch_*.txt`。
- CI：`cp_smoke.yml`（Min，TLS）；`cp_full.yml`（手动，构建 VA/VSM 并跑非 Min 流程，归档 logs/**）。

## 路径与命令
- CP（TLS 配置）：`controlplane/config/app.yaml`；启动：`controlplane/build/bin/controlplane.exe controlplane/config`。
- VA：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe video-analyzer/build-ninja/bin/config`。
- VSM：`video-source-manager/build/bin/VideoSourceManager.exe 127.0.0.1:7070`。
- 冒烟（TLS）：`pwsh tools/run_cp_smoke.ps1 -BaseUrl http://127.0.0.1:18080 -CfgDir controlplane/config`。
- mTLS：`pwsh tools/test_mtls_connectivity.ps1`、`pwsh tools/test_mtls_negative.ps1`。
- SSE Soak：`pwsh tools/run_cp_sse_soak_tls.ps1 -Sec 120`。

## 约束与注意
- C++ 禁止链接 Anaconda；Windows 构建前终止同名进程以免 LNK1104；不要随意清理构建目录。
- 前端 dev 联调需重启 `npm run dev` 使代理与 .env 生效；分析页至少需选择来源/管线。

## 已知问题与规避
- 订阅 400：检查是否缺少 `stream_id/profile/source_uri`（或 `source_id`）；前端已补齐兜底，但首次需确认来源存在。
- 媒体未起播：未见 /whep 201 时，先执行编排正向用例，待 VA 管线 ready 再刷新。

## 结论
- 现已具备：TLS/mTLS、编排正/负、方法维度指标、SSE Soak（2 分钟）、VA REST 收口、前端联调修复与 CI 入口。后续可扩展更长 Soak 与更多 UI 校验。
