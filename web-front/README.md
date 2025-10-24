# web-front

基于 Vue 3 + TypeScript + Vite + Element Plus 的前端最小实现，覆盖 Dashboard / Pipelines / Sources / Models / Observability / Settings / About。

- 启动：
  - `npm i`
  - `npm run dev`（默认代理 `/api` 和 `/metrics` 到 `VITE_API_BASE`，开发默认 `http://127.0.0.1:8082`）
- 主要能力：
  - Pipelines 列表、退订、切换模型
  - Sources 订阅/退订
  - Models 列表
  - Observability 拉取 `/metrics` 文本（可自动刷新）
  - Settings 设置引擎参数（/api/engine/set）、控制面 ApplyPipeline(s)（REST）
  - Dashboard 包含 WHEP 播放小部件（需要后端提供 WHEP 端点）

注意：引擎覆写在后端为全局生效；WHEP 播放示例为最简实现（无 trickle）。


## Admin 与告警联动（M2）

- 访问路径：/admin
  - 展示：Registry Preheat、WAL 摘要与 Tail、Quotas/ACL（含 overrides 表）
  - 操作：下载 Prometheus 告警规则、可选跳转 Grafana

- 环境变量（开发模式，建议新建 web-front/.env.development）：
  - VITE_API_BASE=http://127.0.0.1:8082（VA 后端地址，用于代理 /api 与 /metrics）
  - VITE_GRAFANA_BASE=http://127.0.0.1:3000（可选，用于 Admin 页“打开 Grafana”按钮）

- 告警规则下载：
  - 前端静态资源路径：/alerts/va_alerts.yaml
  - 源文件：web-front/public/alerts/va_alerts.yaml

- 启动预览：
- 
pm i && npm run dev
  - 浏览器打开 http://127.0.0.1:5173/admin（端口以本地 Vite 输出为准）


