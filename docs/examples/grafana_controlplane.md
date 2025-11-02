## Grafana：Controlplane 仪表盘与告警

本页说明如何导入控制平面仪表盘与告警规则，基于 Prometheus + Grafana。

### 指标前提
- Controlplane 暴露 `/metrics`，包含：
  - `cp_request_total{route,method,code}`（counter）
  - `cp_sse_connections`（gauge）
  - `cp_sse_reconnects`（counter）
  - `cp_request_duration_ms_bucket/sum/count{route,method}`（histogram，固定桶：5/10/25/50/100/250/500/1000/2500/5000 ms）
  - `cp_backend_errors_total{service,code}`（counter）

### 导入仪表盘
1) Grafana → Dashboards → Import → 上传文件 `grafana/controlplane_dashboard.json`
2) 选择 Prometheus 数据源（默认名通常为 `Prometheus`）

包含面板：
- SSE Connections（当前值）
- SSE Reconnects（5 分钟增量）
- Requests by route/method/code（RPS 折线）
- 5xx ratio（5 分钟窗口，阈值 1%、5%）
- Top routes（5 分钟窗口，Top-10）

### 告警规则（Prometheus 规则文件）
- 文件：`grafana/alerts/controlplane_rules.yaml`
- 规则：
  - `CPHigh5xxRatio`：5 分钟 5xx 占比 > 1%（warning，持续 5m）
  - `CPSseConnectionsZero`：`cp_sse_connections` 连续 10 分钟为 0（warning）

使用方式：
- 若 Prometheus 使用基于文件的 rule 配置，将该文件路径加入 `rule_files`。
- 若使用 Alertmanager，请确保已正确对接路由与接收器（本项目不包含 Alertmanager 配置）。

### 本地验证建议
- 并发用例：`controlplane/test/scripts/check_cp_sse_concurrency.py`（默认 3 客户端/5 秒）
- 长连 SOAK：`controlplane/test/scripts/soak_cp_sse_watch.py`（默认 60 秒，可通过 `CP_SSE_SOAK_SEC` 设置）
- 最小冒烟：`tools/run_cp_smoke.ps1 -Min [-BaseUrl http://127.0.0.1:18080]`

