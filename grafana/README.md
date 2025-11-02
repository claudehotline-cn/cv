# Grafana 可视化与告警（VA 订阅）

- 导入仪表盘：`dashboard-va-subscriptions.json`
- 配置 Prometheus 告警规则：`prometheus-alert-rules.yml`

指标假定：
- 计数器 `va_subscriptions_total{status}`（status∈pending|ready|failed|cancelled）
- 直方图 `va_subscription_duration_seconds`（_bucket/_sum/_count）
- 当前在途 `va_subscriptions_inflight`

建议阈值（可按环境调整）：
- 失败率 > 5%（5 分钟窗口）
- 订阅 P95 时延 > 8 秒（10 分钟）
- 在途订阅数 > 50（10 分钟）

导入步骤：
- Grafana：Dashboards → Import → 上传 JSON
- Prometheus：加载 `prometheus-alert-rules.yml`（或 Alertmanager 规则），重载配置

