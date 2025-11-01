# 监控编排（Prometheus + Grafana）

本目录提供最小可用的 Docker 编排：Prometheus（抓取 CP/VA 指标）+ Grafana（可视化）。

## 目录结构

```
tools/docker/monitoring/
  docker-compose.yml
  prometheus/
    prometheus.yml
  grafana/
    provisioning/
      datasources/
        prom.yaml
```

## 启动

1) 确认宿主服务可达（示例）：
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

> 注：容器内通过 `host.docker.internal` 访问宿主机服务；如在 Linux 原生 Docker 环境可改为宿主网关 `172.17.0.1`。

## Prometheus 配置

- 默认抓取：自身 + Controlplane(18080) + VideoAnalyzer(8082)。
- 如 VA 改用独立 9090 端口，请编辑 `prometheus/prometheus.yml`，启用 `video-analyzer-prom`，并注释掉 `video-analyzer-http`。
- 修改后热加载：

```
Invoke-WebRequest -Method POST http://localhost:9091/-/reload
```

## 常见问题

- 报错 “Are you trying to mount a directory onto a file”：使用目录对目录挂载（compose 已采用 `./prometheus:/etc/prometheus:ro`），确保宿主 `prometheus/prometheus.yml` 存在且为文件。
- 报错 “field scrape_configs not found”：多为 YAML 缩进/顶层键错误或文件内容不对。可用容器内校验：

```
docker exec -it prometheus promtool check config /etc/prometheus/prometheus.yml
```

- Targets 为 DOWN：先在宿主浏览器确认 `/metrics` 可访问；Windows 防火墙放行端口；Linux 环境将 `host.docker.internal` 改为宿主网关 IP。

