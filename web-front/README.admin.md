# Admin 与告警联动（M2）

- 访问路径：`/admin`
  - 展示：Registry Preheat、WAL 摘要与 Tail、Quotas/ACL（含 overrides 表）
  - 操作：下载 Prometheus 告警规则、可选跳转 Grafana

- 开发环境变量（新建 `web-front/.env.development`）：
  - `VITE_API_BASE=http://127.0.0.1:8082`（VA 后端地址，用于代理 `/api` 与 `/metrics`）
  - `VITE_GRAFANA_BASE=http://127.0.0.1:3000`（可选，用于 Admin 页“打开 Grafana”按钮）

- 告警规则下载：
  - 前端静态资源路径：`/alerts/va_alerts.yaml`
  - 源文件：`web-front/public/alerts/va_alerts.yaml`

- 启动预览：
  - `npm i && npm run dev`
  - 浏览器打开 `http://127.0.0.1:5173/admin`（端口以本地 Vite 输出为准）
