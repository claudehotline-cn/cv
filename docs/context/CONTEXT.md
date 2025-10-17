# 项目对话上下文（2025-10-18）

本文件汇总近期对话的关键结论、系统现状、已知问题与下一步优先事项，便于研发、测试与前端协同。

## 后端现状
- REST 接口全部 DB-only，无回退：失败直接 503 并返回错误文本（前端显式告警）。
  - `/api/logs`、`/api/events/recent`、`/api/sessions`：支持分页 `page/page_size/total`、时间窗 `from_ts/to_ts`、过滤 `pipeline/level/node/stream_id`；`node/stream_id` 支持 CSV → SQL IN。
  - `/api/db/retention/status` 暴露保留策略配置与运行统计。
- /metrics 稳定（Prometheus 0.0.4）：
  - 连接池：`va_db_pool_*`
  - Writer 队列：`va_db_writer_queue_{events,logs}`
  - 保留任务：`va_db_retention_*`
  - 服务端采用非阻塞快照，套接字收发超时已配置。
- 稳定性修复：HTTP 头解析空行与 Expect: 100-continue、WinSock 超时、SSE 去锁化与 CORS 头。
- 数据库索引：events/logs 增加 `(stream_id, ts desc)`、`(node, ts desc)` 复合索引；统一 MySQL 端口 13306。

## 前端现状
- Logs（DB）：服务端分页，摘要 `X–Y/共N`，CSV 导出；日期变更自动重置到第 1 页。
- Events（DB）：服务端分页与导出已接入；LIVE 仍走 SSE。
- Sessions：默认 30 天时间窗，“清空筛选”，DB 失败显式提示。
- Metrics：
  - MetricsSummary 卡片：DB Pool/Writer/Retention，阈值由 `VITE_WRITER_WARN/DANGER` 配置。
  - MetricsDbPanel 趋势：定时轮询 /metrics，支持 CSV 导出。
  - MetricsQueryPanel：单点快照查询（后续可扩展窗口采样）。
- 构建与运行：`.env.development/.env.production` 配置 `VITE_API_BASE`；提供预览重启脚本避免 Vite 预览陈旧切片 404。

## 测试与取证
- MySQL Shell：`C:\\Program Files\\MySQL\\MySQL Shell 8.4\\bin\\mysqlsh.exe`。
- Windows 脚本：`tools/win/restart_backend.ps1`、`restart_frontend_preview.ps1`、`probe_api.ps1`（含 /metrics、/retention/status 探测）。
- Playwright MCP：完成 DB 模式取证（Logs/Events/Sessions）；证据与 API 探测 JSON 存于 `docs/memo/assets/2025-10-16/`、`2025-10-17/`。

## 已知问题/注意事项
- 偶发 Vite 预览陈旧切片 404 → 使用前端预览重启脚本并强刷。
- Windows 链接期占用（LNK1104）→ 重启/停止 EXE 再构建。
- SSE 未启用时控制台报错属预期；DB 视图不受影响。
- 配置目录需与运行二进制一致（`build-ninja/bin/config`）。

## 近期优先事项
1) 修复并运行 `tools/win/db_bench_index.ps1`（变量插值 `$User@${Host}:$Port` 与引号），产出“批量插入 + 查询耗时” JSON 证据。
2) 生成并维护 `docs/context/ROADMAP.md`（≤800 词），与 CONTEXT 事实保持一致。
3) Playwright 追加多值过滤（node/stream_id CSV）与分页取证，保存证据。
4) Metrics 页完善阈值高亮与异常导出核验；必要时扩展短窗口采样方案。

