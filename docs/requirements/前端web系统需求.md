**项目**：视频分析控制台（Web）
 **技术栈**：Vue 3 + TypeScript + Vite + Pinia + Vue Router + **Element Plus**（按需自动导入）
 **布局**：上方 Header、左侧导航、右侧内容、底部 Footer
 **后端形态**：控制平面（Control Plane）提供 REST 接口与 WHEP 播放端点；`video-analyzer`、`video-source-manager` 为 Agent
 **媒体传输**：浏览器通过 **WebRTC / WHEP** 拉取后端输出的视频轨（原始/分析后）；支持**分析开/关**与**模型热切换**

------

## 1. 背景与目标

- 为视频分析平台提供统一的**编排与运维 GUI**：视频源管理、Pipeline 图形化编排、分析开/关、**模型热切换**、运行态观测（指标/日志/事件）、WHEP 实时播放。
- 前端仅对接 **控制平面 CP** 的 REST 与 WHEP 端点；不直接访问 Agent 的 gRPC。
- **本阶段不做角色/权限**，但整体设计需便于后期扩展 RBAC 与多租户。

------

## 2. 范围与边界

**范围**

- 页面：Dashboard、Pipelines、Sources、Models、Observability（Metrics / Logs / Events）、Settings、About。
- 播放：WebRTC(WHEP) 播放器；**分析开/关热切换**、**模型热切换**。
- 与 CP 的接口：REST/JSON +（可选）SSE 事件流；WHEP SDP 交互。

**暂不包含**

- 登录鉴权、组织/租户、审计细粒度（后续阶段引入）。
- 直接 gRPC 调用（由网关或 CP 转 REST/JSON）。

------

## 3. 术语

- **CP**：Control Plane（控制平面）。
- **Pipeline**：Source→Preprocess→Model→Postproc→Overlay→Sink 的有序处理流或 DAG。
- **WHEP**：WebRTC-HTTP Egress Protocol（浏览器**下行拉流**）。
- **WHIP**：WebRTC-HTTP Ingest Protocol（上行推流，供后端/边缘）。

------

## 4. 总体架构与交互

```
[Browser: Vue3 SPA + Element Plus]
         │  HTTPS (REST/JSON) + WHEP
         ▼
[Control Plane API (独立部署)]
   ├─ /api/v1/pipelines        ← 编排/热更/Drain
   ├─ /api/v1/sources          ← 源管理/健康
   ├─ /api/v1/models           ← 模型清单/上传/登记
   ├─ /api/v1/analysis         ← 分析开/关状态控制
   ├─ /api/v1/metrics|logs|events  ← 观测与事件
   └─ /api/v1/play/whepUrl     → 返回带 token 的 WHEP 播放 URL
```

------

## 5. 用户场景与关键用例

1. **巡检播放**：选择 Source → 播放原始视频；切换“分析”开关 → 切到**分析后轨**；在不停止播放的前提下切换不同模型对比效果 → 停止分析回到原始视频。
2. **上线发布**：图编辑器中拖拽节点与连线 → 参数表单校验 → 一键 Apply → 观察 FPS/延迟/错误 → 必要时回滚。
3. **异常定位**：Dashboard 告警 → 一键跳 Pipeline 详情 → 查看最近 Logs/Events → 锁定失败节点。

------

## 6. 信息架构与导航（左侧）

- **Dashboard** `/dashboard`
- **Pipelines** `/pipelines`（列表/详情/图编辑/变更历史/内嵌播放与分析控制）
- **Sources** `/sources`（列表/健康、Attach/Detach）
- **Models** `/models`（清单/上传/热更）
- **Observability** `/observability`（Metrics/Logs/Events）
- **Settings** `/settings`（系统信息与自检）
- **About** `/about`

------

## 7. 组件与 UI 规范（基于 Element Plus）

### 7.1 全局与布局

- **Header**：`<el-header>` + `<el-breadcrumb>`（路径）、全局搜索（`<el-autocomplete>`）、构建号 `el-tag`。
- **Sidebar**：`<el-aside>` + `<el-menu>`（分组图标：`@element-plus/icons-vue`），支持折叠。
- **Content**：`<el-main>` 承载路由视图；页面内常用容器用 `<el-card>` / `<el-tabs>`。
- **Footer**：`<el-footer>` 显示版权/版本与连接状态（`el-tag`）。
- **主题**：通过 CSS 变量定制 Element Plus 主题色，支持暗色（切换写入 `:root` 变量）。
- **状态控件**：加载用 `ElLoading.service`；空态 `el-empty`；错误 `el-result`；提示 `el-message` / `el-notification`；二次确认 `el-popconfirm`。

### 7.2 页面级组件映射

| 页面               | 主体组件                                                     | 表单/交互                                                    | 反馈                         |
| ------------------ | ------------------------------------------------------------ | ------------------------------------------------------------ | ---------------------------- |
| Dashboard          | `el-row/el-col` + `el-card` + ECharts                        | 时间范围 `el-date-picker`                                    | `el-skeleton`、`el-empty`    |
| Pipelines 列表     | `el-table` + `el-pagination`                                 | 行内操作 `el-dropdown`                                       | `el-message`, `el-drawer`    |
| Pipeline 详情/编辑 | `el-tabs`（信息/拓扑/观测/历史）+ 图编辑器（自研/AntV X6 外挂） | 参数表单 `el-form`/`el-form-item`/`el-select`/`el-input-number` | `el-alert`、`el-steps`       |
| Sources            | `el-table` + `el-descriptions`                               | Attach/Detach `el-dialog` + `el-form`                        | `el-message-box`             |
| Models             | `el-table` + 上传 `el-upload`                                | 元数据编辑 `el-form`                                         | 进度 `el-progress`           |
| Observability      | 卡片 `el-card` + ECharts                                     | 过滤 `el-select`/`el-input`                                  | `el-empty`                   |
| 播放/分析面板      | `el-card` 视频容器 + `el-select`（源/模型）+ `el-switch`（分析开关） + `el-button`（刷新） | 顶部工具条                                                   | 顶部 `el-alert`/`el-message` |

> **按需自动导入**：配置 `unplugin-vue-components`（Element Plus Resolver）与 `unplugin-auto-import`，确保 Tree-shaking。

------

## 8. 功能需求（详细）

### 8.1 Dashboard

- **统计卡**：运行中/异常 Pipelines、在线 Sources、平均 FPS/延迟（`el-card` + 大号数字）。
- **曲线**：FPS、延迟 P50/P95、错误率 TopN（ECharts，懒加载）。
- **事件流**：`el-timeline` 展示最近告警，SSE 实时追加。

### 8.2 Pipelines

- **列表**：`el-table`（name、revision、phase、fps、latency、updated_at）+ 顶部筛选（`el-input`、`el-select`）+ 分页。
- **详情**：
  - `el-tabs`：信息、**拓扑编辑**、观测、历史。
  - **拓扑编辑**：节点库抽屉（`el-drawer`）→ 拖拽到画布（外部库）→ 右侧参数 `el-form` → 保存为“草稿”。
  - **校验**：`el-form` 规则 + 自定义校验函数（如输入尺寸、provider/IOBinding 开关合法性）。
  - **Apply**：`el-steps` 展示任务进度（编译→下发→健康→完成），失败显示 `el-result` 并支持回滚。
  - **内嵌播放与分析控制**（见 8.5）。

### 8.3 Sources

- **列表**：`el-table` + `el-tag`（Phase）+ `el-progress`（FPS/丢包可选柱条可视化）。
- **Attach**：`el-dialog` + `el-form`（uri、decoder、fps、重连策略）；
- **Detach**：`el-popconfirm` 二次确认；
- **健康详情**：`el-descriptions` + 曲线卡片。

### 8.4 Models

- **清单**：`el-table`（名称/版本/大小/provider 兼容性标签）。
- **上传/登记**：`el-upload`（拖拽/按钮）或 URI 方式（`el-input`）。
- **热更**：右侧抽屉选择 Pipeline 与节点（`el-select`），执行后在 Pipeline 详情页观察指标变化。

### 8.5 播放与分析控制（关键）

- **UI**：
  - 顶部工具条（`el-card` 内）：
    - Source 选择：`el-select`（支持搜索，展示 Phase `el-tag`）
    - 分析开关：`el-switch`（开=分析后轨，关=原始轨）
    - 模型选择：`el-select`（仅在开=分析时启用）
    - 刷新：`el-button`（手动软重连）
    - 状态标签：`el-tag`（Raw / Analyzed）
  - 播放面板：视频容器（自定义 `<WhepPlayer />` 包裹在 `el-card` 中）+ 码率/FPS 小徽标（`el-badge`/`el-statistic`）。
- **行为**：
  - **开始分析**：`POST /analysis/start` → 理想情况下轨道无缝切换；不理想时 `trackended` → 自动软刷新。
  - **停止分析**：`POST /analysis/stop` → 切回原始轨。
  - **模型热切换**：`POST /pipelines/{name}:hotswap` → 画面保持或短暂抖动；UI 保持状态。
  - **源切换**：重新获取 WHEP URL 并重建会话（旧会话释放）。
- **异常处理**：
  - 3 秒内未恢复画面 → 顶部 `el-alert`，并在播放器右上角展示 `el-button text`“重试”。
  - 连续 3 次失败 → `el-notification` 提示并提供“查看日志”跳转。

### 8.6 Observability

- **Metrics**：查询表单（`el-form inline`）+ 常用模板按钮（`el-button-group`）+ 图表卡片（`el-card`+ECharts）。
- **Logs**：`el-table` 或虚拟列表；按 Pipeline/Level/时间筛选；实时尾随（SSE/WS）。
- **Events**：`el-timeline` + 标签筛选；支持导出 CSV。

### 8.7 Settings / About

- Settings：`el-descriptions` 展示 CP/WHEP URL、构建号、自检结果。
- About：`el-descriptions` + 文本与链接、版本/许可证等。

------

## 9. 接口契约（前端 → CP）

> 统一前缀：`${VITE_CP_BASE_URL}`；统一错误：`{ code, message, details? }`；长任务返回 `task_id` 并轮询 `/tasks/{id}` 或 SSE。

### 9.1 Pipelines

- `GET /api/v1/pipelines?page=&page_size=&q=`
- `GET /api/v1/pipelines/{name}`
- `POST /api/v1/pipelines:apply`（提交期望态）
- `POST /api/v1/pipelines/{name}:drain` → `{ "timeout_sec": 30 }`
- `POST /api/v1/pipelines/{name}:hotswap` → `{ "node": "det", "modelUri": "models/yolov12m-int8.onnx" }`
- `DELETE /api/v1/pipelines/{name}`

**Pipeline Spec（JSON 示例）**

```
{
  "name": "lineA-entrance",
  "source_ref": "source/rtsp-entrance-01",
  "nodes": [
    {"name":"pre","type":"resize_pad","params":{"size":"1280x736","keep_ratio":"true"}},
    {"name":"det","type":"onnx_model","params":{"modelUri":"models/yolov12s-int8.onnx","provider":"tensorrt","iobinding":"true","zeroCopy":"true"}},
    {"name":"nms","type":"nms","params":{"iou":"0.6","conf":"0.35","maxDet":"300"}},
    {"name":"ovl","type":"cuda_overlay","params":{"palette":"brand-dark","thickness":"2"}},
    {"name":"out","type":"whep_out","params":{"whepUrl":"${VITE_WHEP_BASE_URL}/lineA","fps":"25"}}
  ]
}
```

### 9.2 Sources

- `GET /api/v1/sources`（id、name、uri、phase 等）
- `POST /api/v1/sources:attach` → `{ "attach_id": "...", "source_uri": "rtsp://...", "pipeline_id": "lineA", "options": {"decoder":"nvdec"} }`
- `POST /api/v1/sources:detach` → `{ "attach_id": "..." }`
- `GET /api/v1/sources/health`

### 9.3 分析控制（关键）

- `GET /api/v1/analysis/state?sourceId=cam01` → `{ "analyzing": true, "pipeline": "lineA", "model": "models/yolov12s-int8.onnx" }`
- `POST /api/v1/analysis/start` → `{ "sourceId":"cam01", "pipeline":"lineA", "modelUri":"models/yolov12s-int8.onnx" }`
- `POST /api/v1/analysis/stop` → `{ "sourceId":"cam01" }`

### 9.4 模型

- `GET /api/v1/models`；`POST /api/v1/models`（上传/登记）

### 9.5 播放端点（WHEP）

- `GET /api/v1/play/whepUrl?sourceId=cam01` → `{ "whepUrl":"https://edge.example.com/whep/play?source=cam01&token=..." }`

> **期望**：同一 sourceId 的 `whepUrl` 稳定；分析开/关/热切换尽量在同一轨道上无感切换（或触发 `track ended` 以便前端刷新）。

### 9.6 观测与任务

- `GET /api/v1/metrics/query?m=...&range=...`；`GET /api/v1/metrics/raw`
- `GET /api/v1/logs?pipeline=&level=&since=`
- `GET /api/v1/events/recent` / `GET /api/v1/events/stream`（SSE）
- `GET /api/v1/tasks/{id}` → `{ status, progress, message }`

------

## 10. 状态管理（Pinia 关键 Store）

- `useAppStore`：`{ cpBaseUrl, whepBaseUrl, buildRev, theme, selfTest }`
- `usePipelinesStore`：列表、当前详情、草稿、任务进度、Apply/Drain/Hotswap 动作
- `useSourcesStore`：源列表、健康、Attach/Detach
- `useModelsStore`：模型列表、上传任务
- `useMetricsStore`：指标查询缓存
- `useAnalysisStore`：`{ currentSourceId, analyzing, currentPipeline, currentModelUri, currentWhepUrl }` + `startAnalysis/stopAnalysis/hotswapModel/setSource`

------

## 11. 交互与时序（热切换）

**开启分析**

1. `POST /analysis/start` → 后端切换到**分析后轨** → 画面理想不断流；若 `track ended` → 前端播放器自动 `refresh()`；右上 `el-tag` 变为 “Analyzed”。

**停止分析**

- `POST /analysis/stop` → 切回原始轨；同上规则处理刷新。

**模型热切换**

- `POST /pipelines/{name}:hotswap` → 期望画面连续；前端保持会话；失败则 `el-notification` 并保留旧模型。

**源切换**

- 根据新 `sourceId` 获取 `whepUrl` → 释放旧会话 → 启动新会话；若分析状态为开，则自动 `startAnalysis()` 与新源对齐。

------

## 12. 性能与稳定性

- **Core Web Vitals**：LCP ≤ 2.5s、INP < 200ms、CLS < 0.1。
- **资源分包**：图表（ECharts）、图编辑器（X6/Cytoscape）、Element Plus 自动按需引入。
- **Loading 策略**：表格/图表在首次加载显示 `el-skeleton`/`el-empty`；播放面板首帧超 2s 显示 `el-alert`。
- **重连**：播放器失败指数退避（最多 3 次），`el-message` 告知当前动作。

------

## 13. 安全与兼容

- **最小集**：全站 HTTPS；WHEP URL 短期 token；前端不持久化长 token。
- **XSS/安全编码**：所有字符串渲染使用 Vue 绑定；禁止 `v-html`（除非严格转义）。
- **浏览器**：Chrome/Edge ≥ 114；Safari 兼容性根据后端编码策略另测（H.264/AV1）。

------

## 14. 可观测性（前端自身）

- 接口失败率、首屏耗时、播放器错误事件上报（RUM）；前端日志采样 1% 上送（可由 CP 暴露接收端点）。

------

## 15. 测试计划

- **单元（Vitest）**：API 封装、Pinia Store、表单校验、热切换状态机。
- **组件（Cypress CT）**：GraphEditor 节点/连线、WhepPlayer 切源/开关/热切换。
- **E2E（Cypress）**：创建 Pipeline → Apply → 播放 → 开启分析 → 模型热切换 → 停止分析 → 删除。
- **覆盖率**：语句/分支 ≥ 80%。

------

## 16. 工程与目录

```
webapp/
  ├─ index.html
  ├─ vite.config.ts                   # 别名 & Element Plus 自动导入
  ├─ auto-imports.d.ts / components.d.ts
  ├─ .env.development / .env.production
  ├─ src/
  │  ├─ main.ts
  │  ├─ App.vue                       # Header/Sidebar/Content/Footer
  │  ├─ router/index.ts
  │  ├─ api/http.ts                   # fetch 封装（超时/重试/拦截器）
  │  ├─ api/cp.ts                     # 对应第9节接口
  │  ├─ stores/ (app/pipelines/sources/models/metrics/analysis)
  │  ├─ views/ (Dashboard/Pipelines/Sources/Models/Observability/Settings/About)
  │  ├─ widgets/
  │  │   ├─ GraphEditor/              # 图编辑器封装
  │  │   └─ WhepPlayer/               # WHEP 播放器
  │  ├─ components/                   # 表格/表单/对话框/卡片
  │  ├─ assets/ styles/ utils/ i18n/
  └─ tests/  cypress/
```

**Vite & Element Plus 建议配置**（要点）

- 安装：`element-plus`、`@element-plus/icons-vue`、`unplugin-vue-components`、`unplugin-auto-import`
- `vite.config.ts`：
  - `Components({ resolvers: [ElementPlusResolver()] })`
  - `AutoImport({ resolvers: [ElementPlusResolver()] })`
- 图标：在 `main.ts` 全局注册常用图标或按需导入。

------

## 17. 里程碑与验收

**M0**：脚手架 + 布局（Element Plus）+ Dashboard（Mock）+ WHEP 最小播放器 → **验收**：首屏 ≤ 2.5s，视频首帧 ≤ 2s
**M1**：Pipelines 列表/详情（只读）+ Metrics 查询 → **验收**：查询/分页/图表正常
**M2**：图编辑器 + Apply/Drain + Sources/Models + 播放与分析开关/模型热切换 → **验收**：

- 开启/停止分析画面连续或 ≤ 1s 过渡
- 模型热切换成功率 ≥ 95%，失败有回滚提示
**M3**：Logs/Events + 长任务统一通知 + 覆盖率达标 → **验收**：E2E 主链路通过率 ≥ 99%

------

## 18. 风险与对策

- **WHEP 实现差异**：默认走 **非 trickle** 一次性 SDP，必要时降级重试；提供“手动刷新”按钮。
- **轨道切换黑屏**：播放器监控 `connectionState/track ended`，3s 内未恢复自动 `refresh`，并浮层提示。
- **指标高基数**：前端降采样与节流、限制一次渲染的序列数量，避免卡顿。
- **UI 一致性**：统一使用 Element Plus 设计语言与交互反馈（Loading/Skeleton/Empty/Error）。

------

### 附：关键交互控件（Element Plus 推荐搭配）

- 列表：`el-table`（多选/固定列/横向滚动）+ `el-pagination`
- 表单：`el-form`（`rules` 校验）+ `el-input`/`el-select`/`el-switch`/`el-input-number`
- 弹层：`el-dialog`、`el-drawer`、`el-popconfirm`
- 信息展示：`el-descriptions`、`el-result`、`el-alert`、`el-tag`、`el-statistic`
- 反馈：`ElLoading.service`、`el-message`、`el-notification`、`el-progress`
- 导航：`el-breadcrumb`、`el-menu`、`el-tabs`、`el-steps`
- 其他：`@element-plus/icons-vue`（如 `VideoCameraFilled`, `Cpu`, `DataLine`, `Warning` 等）

------

**说明**：本版本为“**Element Plus 实施版**”的完整需求分析，覆盖业务、接口、UI 规范、交互流程、工程与验收标准。你可以据此直接启动前端实现；若需要，我可以进一步给出 **App.vue 布局骨架、Pinia Store 模板、WHEP 播放器与分析控制面板的最小代码**（包含 Element Plus 组件的实际用法）以便快速落地。