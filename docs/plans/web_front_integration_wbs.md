# Web-Front 对接 WBS（最小可用）

## 里程碑与交付物

- M1 API 对接与总览（1 天）
  - 交付：
    - 顶栏 Runtime/Summary 对接（/api/va/runtime、/api/_metrics/summary）
    - Dashboard 卡片改为真实数据（Summary）
    - API 封装：getEngineSchema/getMetricsSummary/getVaRuntime
  - 验收：顶栏与总览 5s 刷新，失败有错误提示

- M2 Engine 表单（Schema 驱动）（1–2 天）
  - 交付：
    - EngineForm 组件（根据 /api/ui/schema/engine 动态渲染）
    - Settings 页对接保存（POST /api/control/set_engine；若未就绪，临时 /api/engine/set）
    - 字段校验/默认值展示
  - 验收：保存成功返回 200；Runtime 变化即时可见

- M3 发布/切换向导（1 天）
  - 交付：
    - Release.vue（模型/版本/目标 pipeline/node → 预览 → 执行）
    - provider=triton 路径：先 SetEngine 覆盖 triton_model/version → HotSwap（model_uri="__triton__"）
    - 非 triton 路径：HotSwap（model_uri=文件路径/URI）
  - 验收：成功后 Pipelines 刷新可见；失败有回执与可重试

- M4 模型库与仓库操作（1 天）
  - 交付：
    - Models 列表→“加载/卸载/轮询”按钮（/api/repo/load|unload|poll）
    - Ensemble 结构说明（`ens_*` 静态渲染）
  - 验收：仓库操作返回 OK；UI 状态反馈正确

（配合项）后端路由补齐：
- POST /api/control/set_engine（映射 AnalyzerControl.SetEngine）
- POST /api/repo/{load,unload,poll}（映射 RepoLoad/RepoUnload/RepoPoll）

## 验收与回归

- 功能验收：
  - /dashboard 顶栏与卡片为真实数据
  - /engine 表单可保存；字段校验正确
  - /release 成功切换（triton/非 triton 路径）
  - /models 可执行仓库加载/卸载
- 回归：
  - 失败请求错误提示、可重试
  - 环境切换（CP 基地址）

## 风险与缓解

- 后端路由未就绪 → 临时沿用旧接口（/api/engine/set）；完成后切换
- 权限/跨域 → 统一 http 封装与 dev 代理；引入 Bearer token 头
- 指标来源不足 → 以 Summary 卡片为主，留出 Grafana 链接

