# Grafana 面板（Video Analyzer）

- 面板文件：`va_dashboard.json`
- 数据源：Prometheus（导入时可选择或映射至实际数据源）。

## 导入步骤
1. 打开 Grafana → Dashboards → New → Import。
2. 上传 `va_dashboard.json` 文件，选择 Prometheus 数据源，保存。

## 指标覆盖
- 队列与在途：`va_subscriptions_queue_length`、`va_subscriptions_in_progress`。
- 总时长直方图 p95：`va_subscription_duration_seconds_bucket`（通过 histogram_quantile 聚合）。
- 分阶段 p95：`va_subscription_phase_seconds_bucket`（opening/loading/starting）。
- WAL：`va_wal_failed_restart_total`。
- 预热：`va_model_preheat_enabled`、`va_model_preheat_warmed_total`、`va_model_preheat_duration_seconds_bucket`。
- 配额：`va_quota_dropped_total`、`va_quota_would_drop_total`（建议使用 `sum(rate(...[5m]))`），`va_quota_enforce_percent`（当前生效的执行比例）。

## 备注
- 面板为最小可用示例，可按需增减维度与时间窗口。
- 如需限制指标基数，请在后端侧谨慎添加标签，避免高基数引发卡顿与高内存。
