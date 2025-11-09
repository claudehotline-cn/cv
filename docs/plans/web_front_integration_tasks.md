# Web-Front 对接任务清单（Executable Tasks）

## M1 API 对接与总览

- [ ] M1-T1 API 封装
  - 文件：`web-front/src/api/cp.ts`
  - 动作：新增 `getEngineSchema`(GET /api/ui/schema/engine)、`getMetricsSummary`(GET /api/_metrics/summary)、`getVaRuntime`(GET /api/va/runtime)
  - 验收：方法可调用并返回预期键位

- [ ] M1-T2 顶栏 Runtime/Summary 对接
  - 文件：`web-front/src/components/chrome/TopHeader.vue`、`web-front/src/stores/app.ts`
  - 动作：每 5s 拉取 runtime/summary；显示 provider/gpu_active/requests/cache
  - 验收：UI 实时刷新；失败展示错误提示

- [ ] M1-T3 Dashboard 卡片改造
  - 文件：`web-front/src/views/Dashboard.vue`、`web-front/src/components/analytics/*`
  - 动作：卡片数值来源切到 `/api/_metrics/summary`
  - 验收：刷新后为真实数据

## M2 Engine 表单（Schema 驱动）

- [ ] M2-T1 EngineForm 组件
  - 文件：`web-front/src/components/forms/EngineForm.vue`
  - 动作：根据 `getEngineSchema().data.fields[]` 动态渲染（bool/int/string/enum）
  - 验收：字段渲染正确、默认值展示

- [ ] M2-T2 Settings 对接保存
  - 文件：`web-front/src/views/Settings.vue`
  - 动作：集成 EngineForm；提交调用 `POST /api/control/set_engine`（暂 fallback /api/engine/set）
  - 验收：200 返回；顶部 Runtime 变化

- [ ] M2-BE1 后端路由：set_engine（配合）
  - 文件：`controlplane/src/server/main.cpp`
  - 动作：新增 `POST /api/control/set_engine` → 映射 AnalyzerControl.SetEngine
  - 验收：前端提交成功

## M3 发布/切换向导

- [ ] M3-T1 Release 页面与路由
  - 文件：`web-front/src/views/Release.vue`、`web-front/src/router/index.ts`
  - 动作：向导三步（选择→预览→执行）；完成后刷新 Runtime/Pipelines
  - 验收：triton/非 triton 路径均可成功发布

- [ ] M3-T2 Release 调用封装
  - 文件：`web-front/src/api/cp.ts`
  - 动作：封装 release：provider=triton → set_engine + hotswap("__triton__")；否则 hotswap(URI)
  - 验收：返回 OK；错误提示清晰

## M4 模型库与仓库操作

- [ ] M4-T1 Models 按钮
  - 文件：`web-front/src/views/Models.vue`
  - 动作：为每行添加 Load/Unload/Poll 按钮；调用 /api/repo/*
  - 验收：返回 OK；状态提示

- [ ] M4-BE1 后端路由：repo 系列（配合）
  - 文件：`controlplane/src/server/main.cpp`
  - 动作：新增 `POST /api/repo/{load,unload,poll}` 映射 RepoLoad/RepoUnload/RepoPoll
  - 验收：前端按钮可用

## 验收与回归

- [ ] A1 Smoke：`tools/validate/e2e_smoke.sh` 通过（/api/ui/schema/engine、/api/_metrics/summary、/api/va/runtime）
- [ ] A2 发布/回滚演练：使用 `va_release` 与前端发布向导，成功切换并能回滚
- [ ] A3 指标观察：Summary 卡片数值变化合理，失败路径有提示

