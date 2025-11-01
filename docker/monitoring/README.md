# 监控编排（Prometheus + Grafana）

本目录提供最小可用的 Docker 编排：Prometheus（抓取 CP/VA 指标）+ Grafana（可视化）。

## 启动

1) 确认宿主服务可达：
- CP 指标：http://127.0.0.1:18080/metrics
- VA 指标：
  - http 路由：http://127.0.0.1:8082/metrics，或
  - 独立 Prom endpoint：http://127.0.0.1:9090/metrics（按实际启用）

2) 在本目录执行：

```
docker compose up -d
```

3) 访问：
- Prometheus: http://localhost:9091 （Status → Targets 应为 UP）
- Grafana: http://localhost:3000 （默认 admin/admin）

> 注：容器内通过 `host.docker.internal` 访问宿主机服务；如在 Linux 原生 Docker 环境改用宿主网关 `172.17.0.1`。

## Prometheus 配置

- 默认抓取：自身 + Controlplane(18080) + VideoAnalyzer(8082)。
- 如 VA 改用独立 9090 端口，请编辑 `prometheus/prometheus.yml`，启用 `video-analyzer-prom`，并注释掉 `video-analyzer-http`。
- 修改后热加载：

```
Invoke-WebRequest -Method POST http://localhost:9091/-/reload
```

## 常见问题

- 配置解析错误：使用容器内工具校验

```
docker exec -it prometheus promtool check config /etc/prometheus/prometheus.yml
```

- 挂载错误：确保目录对目录挂载 `./prometheus:/etc/prometheus:ro`，且 `prometheus.yml` 为文件。

