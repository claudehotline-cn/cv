# Web-Front 对接设计（最小可用方案）

## 目标与范围

- 目标：为 VA/CP 提供发布、配置、观测、预览的一体化前端页面；优先打通“发布流（上传→Load→Warmup→Alias/HotSwap）”“引擎配置”“运行态观测”“模型库浏览”。
- 范围：基于 Controlplane HTTP API 与已实现的最少新增接口，前端仅消费 HTTP，不直接调用 gRPC。

## 信息架构（IA）

- 导航
  - Dashboard（总览/运行态/指标）
  - Pipelines（订阅/管线列表）
  - Models（模型库/版本/Ensemble 说明）
  - Engine（引擎配置表单）
  - Release（发布/切换/回滚）
  - Metrics（Prom 面板/导出）
  - Sources（VSM 源/探测）
- 全局要素
  - 顶部状态条：VA Runtime（provider/gpu/io/device），CP 请求统计，缓存命中
  - 右上角：环境选择（CP 基地址）、认证（Bearer Token）

## 后端 API 映射

- 已有（CP）
  - GET `/metrics`（Prom）
  - POST `/api/control/apply_pipeline`、`/api/control/apply_pipelines`、`/api/control/hotswap`、`/api/control/status`、`/api/control/drain`
- 新增（已实现）
  - GET `/api/ui/schema/engine`（引擎表单 Schema）
  - GET `/api/_metrics/summary`（CP 指标汇总：请求/错误/缓存）
  - GET `/api/va/runtime`（VA 运行态：provider/gpu_active/io_binding/device_binding）
- 建议新增（HTTP→gRPC 映射，前端不感知 gRPC）
  - POST `/api/control/set_engine` → AnalyzerControl.SetEngine
  - POST `/api/control/release` → 封装 SetEngine + HotSwapModel
  - POST `/api/repo/{load,unload,poll}` → RepoLoad/RepoUnload/RepoPoll

## 页面与组件设计

- Dashboard
  - 卡片：VA Runtime、CP Summary（req/error/cache）、最近管线
  - 行为：跳转 Metrics/Pipelines
- Engine（Schema 表单）
  - 渲染 `/api/ui/schema/engine` 的 fields[]（类型：bool/int/string/enum）
  - 提交：POST `/api/control/set_engine`（键值差异）
- Models（模型库）
  - 列表：name/family/variant/path/版本
  - 行为：仓库 Load/Unload（POST `/api/repo/load|unload`）
  - 详情：`ens_*` 结构图静态说明
- Release（发布/切换）
  - Step1 选择模型/版本/目标 pipeline/node
  - Step2 预览当前→目标差异
  - Step3 执行发布：
    - provider=triton：`set_engine({triton_model,version})` 后 `hotswap(model_uri="__triton__")`
    - 非 triton：`hotswap(model_uri=文件路径)`
- Pipelines
  - 列表：key/stream_id/profile/model_id/fps/running
  - 行为：查看/取消/重建
- Metrics
  - 展示 `/metrics` 文本或 Grafana 链接；导出文本
- Sources（可选）
  - 列表：phase/fps/attach_id；探测与附加

## 状态管理与实时

- 顶栏 Runtime 与 Summary：5s 轮询（可配）
- 列表页：手动刷新 + 30s 背景刷新
- 错误处理：后端错误（映射 gRPC code）弹窗展示，提供重试与复制
- 认证：所有请求带 `Authorization: Bearer <token>`（若配置）

## 发布与回滚交互

- 发布（Release）
  - 提交：`{ pipeline, node, triton_model, triton_model_version? }`
  - 成功：刷新 Runtime 与 Pipelines
- 回滚（Rollback）
  - 前端保留最近一次发布的“上一个模型/版本”，一键回滚
  - 也可直接选择老版本执行 Release

## 前端实现要点

- 技术：Vue 3 + Vite + Element Plus + Pinia（沿用现有 web-front）
- 路由：`/dashboard /engine /models /release /pipelines /metrics`
- 数据：`http`/`cp` API 封装 + 轮询（SWR 思路）
- 组件：
  - `EngineForm`（Schema→表单）
  - `ReleaseWizard`
  - `ModelsTable`/`PipelinesTable`
  - `RuntimeBadge`/`SummaryCards`
- 配置：`.env` 使用 `VITE_CP_BASE_URL` 指向 CP

## 验收与回归

- 打开 `/dashboard`：顶栏 Runtime 正常，Summary 卡片显示请求/缓存
- `/engine`：Schema 表单正确渲染，提交 200
- `/release`：选择模型完成切换，Pipelines 刷新可见变化
- `/models`：列表展示；Load/Unload 调用成功
- `/observability`：Summary 可见，`/metrics` 可打开

## 里程碑与任务拆分

- M1（1 天）：
  - API 封装（getEngineSchema/getMetricsSummary/getVaRuntime）
  - 顶栏 Runtime/Summary 对接
  - Dashboard 卡片对接
- M2（1–2 天）：
  - EngineForm（Schema→表单）
  - Settings 对接 `/api/control/set_engine`
- M3（1 天）：
  - Release 向导（triton/非 triton 路径）
  - 发布完成后刷新
- M4（1 天）：
  - Models 页面仓库操作（待补 `/api/repo/*` 路由）
  - 细节优化（加载态/错误提示）

## 后端补充（配合项）

- 新增 HTTP 路由（映射现有 gRPC）
  - POST `/api/control/set_engine` → AnalyzerControl.SetEngine
  - POST `/api/control/release` → set_engine + hotswap（triton 模式简化）
  - POST `/api/repo/{load,unload,poll}` → RepoLoad/RepoUnload/RepoPoll

## 依赖与风险

- 依赖：CP 已实现 `/api/ui/schema/engine`、`/_metrics/summary`、`/api/va/runtime`；其余路由需补齐
- 风险：
  - 环境差异（无 token/跨域）→ 统一 http 封装与代理
  - 发布流失败（SetEngine/Hotswap）→ 清晰回执与回滚指引

