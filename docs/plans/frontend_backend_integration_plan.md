# 前后端对接与播放器美化实施方案（仅对接 video-analyzer）

本文档按“接口映射 → 页面对接 → 状态更新 → 实施要点”的顺序，给出前后端打通与播放器 UI 美化的落地方案。在不改动现有 WebRTC 播放链路与后端接口语义的前提下，显著提升页面专业度、可用性与观感。

## 概述
- 技术栈：Vue 3 + Pinia + Vue Router + Element Plus；后端为 video-analyzer（REST + WebRTC）。
- 目标：
  - 保持现有播放逻辑与后端接口不变；不破坏已可播放的视频功能。
  - 引入 PlayerCard 外观与状态徽章、连接提示、空/加载/错误态、响应式多流栅格。
  - 将 video-analyzer 的核心 REST 接口映射为 API 层，并在相关页面对接。
  - 指标抽屉按需解析 `/metrics`（只在展开时），展示 FPS/各阶段延时直方图与丢帧原因占比。
- 重要约束：不改 `useVideoStore` 对 `<video>` 的赋值与 WebRTC 连接/请求流流程（`connectWebRTC` / `requestVideoStream` / `disconnectWebRTC` / `setVideoElement`）。

## 接口映射（API Surface）
- 基础环境变量
  - `VITE_API_BASE`：REST 基址（默认 `http://127.0.0.1:8082`）
  - `VITE_SIGNALING_URL`：WebRTC 信令（保持现状）

- 系统与模型
  - `GET /api/system/info` 当前引擎与运行选项
  - `GET /api/system/stats` 系统汇总（总 FPS/帧数/网络）
  - `GET /api/models`、`GET /api/profiles` 模型与 profile 列表
  - `POST /api/engine/set` 切换引擎/设备/IoBinding（仅设置页使用）

- 管道生命周期（核心）
  - `POST /api/subscribe` 启动：`{stream_id, profile, source_uri, [model_id]}`
  - `POST /api/unsubscribe` 停止：`{stream_id, profile}`
  - `POST /api/source/switch` 切源：`{stream_id, profile, source_uri}`
  - `POST /api/model/switch` 切模型：`{stream_id, profile, model_id}`
  - `PATCH /api/model/params` 参数更新：`{stream_id, profile, conf, iou, ...}`
  - `GET /api/pipelines` 当前管道与运行态（分析页/管理页）

- 日志与指标
  - `GET /api/logging`、`POST /api/logging/set` 日志等级/格式/模块级别
  - `GET /api/metrics`、`POST /api/metrics/set` 导出器/扩展标签开关
  - `GET /metrics` Prometheus 文本（per-source 指标、阶段直方图）

## 页面对接（不破坏播放）
- 视频源管理（`web-frontend/src/views/VideoSourceManager.vue`）
  - 列表数据 = 本地源配置 × `GET /api/pipelines` 叠加运行态。
  - 操作：新增/启动 → `POST /api/subscribe`；停止 → `POST /api/unsubscribe`；编辑 URL/切源 → `POST /api/source/switch`。
  - 表单规则（名称/URL/FPS/分辨率）完善；空态与失败反馈。

- 视频分析（`web-frontend/src/views/VideoAnalysis.vue`）
  - 保持现有 `useVideoStore` 工作方式与时序：`setVideoElement(videoRef)` 仍在 `onMounted` 后完成，`connectWebRTC → requestVideoStream` 逻辑不改。
  - 新增 `components/analysis/PlayerCard.vue` 包裹 `<video>`：
    - 顶部状态条（源名、连接状态点：connected/connecting/error）。
    - 右上统计徽章（FPS/分辨率/丢帧提示/延时占位）。
    - 底部控件条（播放/暂停、静音/取消、截图、全屏、置顶）。仅直接操作 `<video>` 属性，不影响 store 业务状态。
  - 指标抽屉：展开时解析 `/metrics`（仅当前源），展示：
    - `va_pipeline_fps{source_id,path}` 折线/数值
    - `va_frame_latency_ms_bucket/_sum/_count{stage,source_id,path}` 直方图 P95/P99
    - `va_frames_dropped_total{source_id,reason}` 饼图占比

- 分析结果（`web-frontend/src/views/AnalysisResults.vue`）
  - 优先使用现有 WebRTC DataChannel 事件流；无事件流时退化为 `/metrics` 趋势图（只读）。
  - 顶部过滤（时间/source/类别/阈值），侧抽屉查看大图与元数据。

- 设置（`web-frontend/src/views/Settings.vue`）
  - 系统信息：`GET /api/system/info` 只读展示。
  - 日志与指标：`GET/POST /api/logging`、`GET/POST /api/metrics`（即时生效）。
  - （可选）引擎切换：`POST /api/engine/set`，保存后提示。

## 状态更新（轮询与抽屉）
- 轮询策略（仅页面前台时）：
  - `GET /api/pipelines`：每 2–5 秒（分析页/管理页）。
  - `GET /api/system/stats`：每 5 秒（全局概览）。
  - `GET /metrics`：仅当“指标抽屉”展开且当前源处于活动状态时，每 5–10 秒。

- 连接与运行态映射：
  - `videoStore.connectionStatus` → PlayerCard 徽章颜色与提示文案（connected/connecting/error）。
  - `pipelines[].running` 与 UI 的“分析中/已停止”状态对齐。

- 错误/重试：
  - REST 失败统一 `ElMessage.error`；提供“重试/查看日志”。
  - WebRTC 断开：提示“已断开”，提供“重新连接”按钮，避免频繁自动重试。

## 实施要点（代码组织与样式）
- API 与 Store
  - `src/api/http.ts`（axios 基础：`baseURL = import.meta.env.VITE_API_BASE`，统一超时/错误处理/拦截器）。
  - `src/api/va.ts`（profiles/pipelines/subscribe/unsubscribe/sourceSwitch/modelSwitch/params/logging/metrics/system）。
  - Pinia 拆分：
    - `usePipelineStore`：管道列表与生命周期操作（REST）。
    - `useSystemStore`：系统信息与统计（REST + 轮询）。
    - `useMetricsStore`：解析 `/metrics` 文本为结构化（仅解析所需指标名前缀；selector 按 `source_id/stage/path`）。
    - 保留 `useVideoStore`（WebRTC/`setVideoElement`/播放控制），不做破坏性改动。

- 播放器美化（不破坏播放链路）
  - 新增：`components/analysis/PlayerCard.vue`、`styles/player.css`、`styles/theme.css`。
  - `<video>` 仍由 `ref` 提供给 store；美化层仅封装样式与本地 UI 控件（静音/全屏/截图）。
  - 响应式栅格：`xs:24 sm:12 lg:8`，多流自动排布；小屏控件折叠至 `More` 菜单。

- `/metrics` 解析
  - 仅在抽屉展开时拉取；关闭即停止；解析仅限需要的指标（前缀过滤），避免开销。
  - P95/P99 可由后端直方图 `_bucket/_sum/_count` 在前端计算，或先以趋势折线简化呈现。

- 可回退与验收
  - 新 UI 开关：在分析页支持 `?classic=1` 或本地“使用旧版播放器”开关，便于快速回退与 A/B 对比。
  - 验收清单（见下）。

## 交付内容
- 代码
  - 新增：`src/api/http.ts`、`src/api/va.ts`、`components/analysis/PlayerCard.vue`、`styles/player.css`、`styles/theme.css`。
  - 修改：`views/VideoAnalysis.vue`（用 PlayerCard 包裹 `<video>`，不改 `ref` 赋值与 store 交互）；`views/VideoSourceManager.vue`（对接 subscribe/unsubscribe/source.switch）与 `views/Settings.vue`（对接 logging/metrics）。
- 文档
  - 在本文件基础上，补充一页“前端新外观开关与问题排查”。

## 进度里程碑
1) 第 1 阶段（基础对接与 UI 外壳）
   - 搭建 API 层与 `usePipelineStore`/`useSystemStore`；提交 PlayerCard 与样式；VideoAnalysis 切换为 PlayerCard 包裹（播放不变）。
2) 第 2 阶段（管理/设置对接与指标抽屉）
   - 源管理页对接 `subscribe/unsubscribe/source.switch`；设置页对接 `logging/metrics`；按需解析 `/metrics` 的指标抽屉。
3) 第 3 阶段（打磨与测试）
   - 响应式优化、空/加载/错误态完善；Bundle 与网络优化；用例回归（播放/切源/开始/停止）。

## 验收清单
- 播放：连接/切源/开始/停止/静音/全屏正常，无额外中断；`setVideoElement` 时序与旧版一致。
- 管道：新增/停止/切源/切模型调用正确，`/api/pipelines` 与 UI 状态一致。
- 指标：抽屉展开展示 FPS/阶段直方图/丢帧占比，关闭停止轮询；解析仅限当前源。
- 设置：`/api/logging` 与 `/api/metrics` 可读可写，并即时生效。

## 风险与回退
- 风险
  - 播放器包裹层变更导致 `ref` 绑定时序变化：通过 e2e 验证 `onMounted → setVideoElement` 顺序，必要时延迟小于 1 帧。
  - `/metrics` 解析带来的性能抖动：仅在抽屉展开时拉取与解析；关闭即停；仅解析所需前缀。
- 回退
  - `?classic=1` 或“使用旧版播放器”开关即时回退旧 UI；不影响播放逻辑与后端接口。

