# 前端 Observability 接入 Grafana/Prometheus 方案

## 目标与范围
- 在不改动现有后端数据路径的前提下，为前端 `Observability/Overview` 与 `Observability/Metrics` 页面引入 Grafana/Prometheus 数据展示能力。
- 统一走 Controlplane（CP）反向代理，避免跨域与直连，便于权限与审计；支持 iframe 嵌入、PNG 渲染兜底，以及后续 KPI 聚合 API。

## 架构与流向
- 前端 → CP：
  - `/grafana/**` → 反代至 Grafana（子路径部署 `/grafana`）
  - `/prom/**` → 反代至 Prometheus（UI/API）
- Grafana（Docker）：开启匿名只读与嵌入；子路径与 RootURL 对齐；可选安装 `grafana-image-renderer` 插件用于 PNG 渲染。
- Prometheus：对外提供 `/api/v1/query(_range)`；CP 统一代理。

## 实施步骤
### 1) Grafana 容器（docker/monitoring）
- 环境变量（典型）：
  - `GF_SECURITY_ALLOW_EMBEDDING=true`
  - `GF_AUTH_ANONYMOUS_ENABLED=true`
  - `GF_AUTH_ANONYMOUS_ORG_ROLE=Viewer`
  - `GF_SERVER_SERVE_FROM_SUB_PATH=true`
  - `GF_SERVER_ROOT_URL=%(protocol)s://%(domain)s/grafana`
  - 可选：`GF_INSTALL_PLUGINS=grafana-image-renderer`

### 2) CP 反向代理（controlplane）
- 在 `controlplane/config/app.yaml` 增加：
  - `grafana.base: http://127.0.0.1:3000/grafana`
  - `prom.base: http://127.0.0.1:9091`
- 在 `controlplane/src/server/main.cpp` 复用现有 HTTP 代理模块，新增：
  - `GET/OPTIONS /grafana/**` → 去前缀反代到 `grafana.base`，透传 CORS/缓存头
  - `GET/OPTIONS /prom/**` → 去前缀反代到 `prom.base`

### 3) 前端 Vite 代理
- 在 `web-front/vite.config.ts` 增加：
  - `'/grafana' -> http://127.0.0.1:18080`
  - `'/prom' -> http://127.0.0.1:18080`

## 页面对接
### A. Overview（首选：iframe 直嵌）
- 新建配置 `web-front/src/config/observability.ts`：
  - `GRAFANA = { base:'/grafana', uid:'<dashboard_uid>', defaultRange:'now-15m', refresh:'10s', panels:[{ id:2, title:'VA Pipeline FPS' }, ...] }`
- 在 `Observability/Overview.vue`：按 `panels` 渲染卡片，iframe URL 形如：
  - `/grafana/d-solo/${uid}?orgId=1&panelId=${id}&from=${from}&to=${to}&theme=light&refresh=${refresh}`
- 优点：开发成本最低、交互能力保留；适合快速上线与运维查看。

### B. Metrics（PromQL 驱动的图/卡片）
- 通过 CP 代理调用 Prom API：
  - 即时值：`GET /prom/api/v1/query?query=<expr>`
  - 时序：`GET /prom/api/v1/query_range?query=<expr>&start=..&end=..&step=..`
- 典型查询示例：
  - WHEP 会话数：`sum(va_webrtc_sessions{service="video-analyzer"})`
  - FPS（1m 窗口均值）：`avg_over_time(va_pipeline_fps_avg[1m])`
  - CP 5xx 率：`rate(http_server_requests_seconds_count{status=~"5..",service="controlplane"}[5m])`
- 在 `Observability/Metrics.vue` 封装 `fetchProm(query, range?)`，用 ECharts/AntV 绘图；参数变更加 300–500ms 防抖；错误统一提示。

### C. 可选兜底：PNG 渲染
- 通过 `/grafana/render/d-solo/...` 获取 PNG，在卡片中 `<img>` 显示；适合概览/低资源页与导出。

### D. 可选演进：CP 聚合 KPI API
- CP 新增：`GET /api/monitor/kpi?from=&to=`，内部并行 PromQL 查询并返回结构化 KPI（帧率分位、会话数、错误率等）。
- 前端概览顶部以 KPI 卡展示；减少前端写 PromQL 的耦合与复杂性。

## 权限与安全
- 匿名只读仅建议用于内网；对外环境应改为 API Key 或“Public dashboard”链接。
- 所有访问通过 CP 统一出口；可在 CP 增加 Referer/Origin 白名单与 Header 过滤。

## 验收清单
- 访问 `http://127.0.0.1:18080/grafana/` 正常（匿名 viewer）。
- `curl "http://127.0.0.1:18080/prom/api/v1/query?query=up"` 返回 `status: success`。
- Overview：2–3 个核心面板 iframe 正常渲染；支持 15m/1h 切换与 10s 自动刷新。
- Metrics：关键 PromQL 有数据，时序图渲染正常，无跨域报错。

## 风险与缓解
- 子路径 404：确保 `GF_SERVER_SERVE_FROM_SUB_PATH` 与 `GF_SERVER_ROOT_URL` 配置正确；浏览器强刷缓存。
- 跨域/嵌入失败：通过 CP 代理规避；Grafana 开启 `ALLOW_EMBEDDING`。
- 资源占用：多 iframe 会消耗资源；高频页可切换 PNG 或 KPI JSON。

