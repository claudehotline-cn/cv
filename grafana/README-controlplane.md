# Controlplane 指标与告警

- 仪表盘：`dashboard-controlplane.json`
- 告警规则：`prometheus-alert-rules-cp.yml`
- 数据源：Prometheus

## 指标速览
- `cp_request_total{route,method,code}`：HTTP 请求计数（含状态码）
- `cp_request_duration_ms_bucket/_sum/_count`：请求耗时直方图（毫秒）
- `cp_sse_connections`、`cp_sse_reconnects`：SSE 活跃数与重连计数
- `cp_backend_errors_total{service,method,code}`：后端 gRPC 错误（VA/VSM），细化到方法维度
- `cp_feature_enabled{feature="controlplane"}`：特性开关

## 建议阈值
- 错误比例：5xx/499/504 > 1%（10m）
- p95 时延：> 750ms（10m）
- SSE 连接：=0（5m）
- 后端错误速率：> 0.1/s（10m）

## 使用步骤
- 在 Grafana → Dashboards → Import 导入 `dashboard-controlplane.json`。
- 将 `prometheus-alert-rules-cp.yml` 加载至 Prometheus 的 rule_files，或合并入现有告警规则文件。
- 确保 Controlplane 暴露 `/metrics`，Prometheus 抓取该 target。

## 常见查询示例
- 每路由请求速率：`sum by (route,method,code) (rate(cp_request_total[5m]))`
- p95 请求耗时：`histogram_quantile(0.95, sum by (route,method,le) (rate(cp_request_duration_ms_bucket[5m])))`
- 后端错误速率：`sum by (service,method,code) (rate(cp_backend_errors_total[5m]))`
