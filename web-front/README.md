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

