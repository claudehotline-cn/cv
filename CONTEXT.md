# CONTEXT（项目上下文与对话要点）

本文档汇总本轮对话中的关键结论、接口与改动、优先事项、测试要点与环境信息，便于跨团队协作与后续推进。若与详细设计存在差异，以 `docs/references/核心流程修改.md` 为准。

## 背景与范围

- 目标：按《核心流程修改》对“前后端 + 控制面（CP）+ VSM”的 pipeline 核心流程进行改造与对齐。
- 前端对接原则：除 WHEP 播放外，前端 Web 仅对接 Control Plane（CP）；已确认“需要”。
- 导航调整：前端侧增加“分析”入口到左侧导航。
- 优先方向：优先推进“VSM caps 扩展 + CP 透出”。

## 仍在遵循的设计文档

- 设计参考：`docs/references/核心流程修改.md`
- 前端需求：`docs/requirements/前端web系统需求.md`
- 前端设计：`docs/design/前端设计.md`

## 已完成（按交接摘要 Memento）

- Control Plane（`video-analyzer`）
  - 新增/增强接口：
    - `GET /api/graphs`：解析并返回每个图的 `requires`（YAML）。
    - `POST /api/preflight`：预检 `source.caps` vs `graph.requires`（fps/分辨率/像素格式）。
    - `GET /api/sources`：聚合 pipelines 并融合 VSM 快照/describe（phase/fps/uri/jitter/rtt/loss/caps）。
    - `GET /api/sources/watch`：长轮询 watch（`rev` + `items`，keepalive）。
    - `GET /api/logs`、`GET /api/logs/watch`：日志（支持 pipeline/level 过滤）。
    - `GET /api/events/recent`、`GET /api/events/watch`：事件（支持 pipeline/level 过滤）。
  - Windows 最小 HTTP 客户端：向 VSM REST 拉取 `/api/source/list` 与 `/api/source/describe`（可用 `VSM_REST_HOST`/`VSM_REST_PORT` 覆盖 `127.0.0.1:7071`）。
  - 端到端验证通过（已运行并返回示例源及 caps）。

- VSM（`video-source-manager`）
  - 采集 caps：`width/height`（OpenCV CAP_PROP）、`fourcc→codec`（best‑effort）、`pix_fmt=BGR`（OpenCV 输出）、`color_space=BT.709`（默认）。
  - `StreamStat` 扩展：`width/height/codec/pix_fmt/color_space` 并在 `Collect()`/`GetOne()` 填充。
  - REST 扩展：
    - `GET /api/source/list`、`GET /api/source/describe` 返回 caps。
    - SSE `GET /api/source/watch` 的 `items` 也包含 caps。
  - 构建、重启通过；`describe` 可见 caps。

- 前端（`web-frontend`）
  - 导航增加“分析”入口（`/pipelines/analysis`）。
  - `dataProvider` 统一走 CP：
    - `listSources/listGraphs/listPipelines/listModels` → `/api` 接口。
    - `preflightCheck` → `/api/preflight`。
    - `logsRecent/logsSubscribe`、`eventsRecent/eventsSubscribe` → `/api/logs(/watch)`、`/api/events(/watch)`（支持 pipeline/level）。
    - `watchSources` → `/api/sources/watch` 长轮询（降级定时刷新）。
  - 分析页：
    - 引入 `GET /api/system/info` 的 `whep_base`，按 “source:Pipeline” 拼接 WHEP URL（保留 mock 回退）。
    - 预检失败时禁用“实时分析”开关。
    - 开始/停止分析调用 CP：`/api/subscribe`、`/api/unsubscribe`（store 已接入）。

## 计划与待办（Next）

- 前端使用 caps 展示与预检联动
  - 在源列表/分析面板显示 `codec/分辨率/pix_fmt/color_space`，并用于禁用态提示。
  - 参考：`web-front/src/views/Sources/List.vue`，`web-front/src/stores/analysis.ts`，`web-front/src/views/Pipelines/AnalysisPanel.vue`。

- 将 CP watch 接口切换为 SSE（保留长轮询兜底）
  - CP：`video-analyzer/src/server/rest.cpp` 中的路由注册与 `handleSourcesWatch`/`handleLogsWatch`/`handleEventsWatch`。
  - 前端：`web-front/src/api/dataProvider.ts` 的 `watchSources`/`logsSubscribe`/`eventsSubscribe` 优先 SSE，回退长轮询。

- logs/events 真实数据源对接（替换现有合成）
  - CP：`handleLogsRecent`/`handleEventsRecent` 对齐真实结构（字段：`ts`、`level/type`、`pipeline`、`node`、`msg`）。

- 分析会话语义与错误处理完善
  - 前端：`startAnalysis/stopAnalysis` 增加错误提示细化、按钮 loading/禁用态。
  - 后端：`/api/subscribe` 的错误冒泡（模型不存在、源不可达、引擎状态变化）。

- caps 完整性与 VSM 获取精度
  - 现状为 best‑effort；后续可用更精确的解复用/RTSP parser 提升准确度。
  - 参考：`video-source-manager/src/adapters/inputs/ffmpeg_rtsp_reader.cc` 初始化 caps 逻辑。

- 文档与变更说明更新
  - 在 `docs/references/核心流程修改.md` 补充“实际落地与接口对齐清单”和 QUICKSTART（后端启动、前端 ENV、VSM 端口）。

## 测试与验证建议

- CP 与 VSM 交互鲁棒性：网络异常/超时/JSON 异常/无 VSM 的降级策略（`/api/sources` 在 VSM 不可用时仅聚合 pipelines）。
- watch 并发与性能：`/api/sources/watch`、`/api/logs/watch`、`/api/events/watch` 大量客户端与超时处理。
- 图 `requires` 解析与预检：YAML 异常、复杂结构、空 caps 兼容（`ok=true` 的降级策略）。
- 分析会话失败路径：模型不匹配、源 URI 无效、引擎状态变化；前端开关与状态恢复。
- 播放兼容：WHEP 实现替换、iOS 自动播放策略（`muted/playsinline`）。

## 已知问题/注意事项

- Windows 构建若进程占用 exe 易导致 `LNK1104`：先停止 `VideoAnalyzer`/`VideoSourceManager` 再链接。
- 使用 `getenv` 产生 MSVC C4996 警告（安全建议），后续可统一封装环境变量读取。
- VSM caps 受 OpenCV 限制：`codec` 四字符码不稳定；`pix_fmt` 为解码输出（BGR），非原始流；`color_space` 默认 BT.709。
- 前端联调：关闭 `VITE_USE_MOCK`；设置 `VITE_API_BASE=http://127.0.0.1:8082`；若未接入真实 WHEP SDK，分析页将使用 mock。

## 构建与运行参考

- 构建前：先将后端进程关闭，确保项目可构建。
- Windows：
  - `video-analyzer` 在 `D:\\Projects\\ai\\cv\\video-analyzer\\build-ninja` 使用 `D:\\Projects\\ai\\cv\\tools\\build_with_vcvars.cmd` 构建。
  - `video-source-manager` 在 `D:\\Projects\\ai\\cv\\video-source-manager\\build` 构建。
- Linux/macOS：`cmake -S . -B build && cmake --build build -j`
- 运行：
  - CP：`build/video-analyzer/VideoAnalyzer`（Windows 选择配置子目录，默认端口 8082）。
  - VSM：`video-source-manager/build/bin/VideoSourceManager`（默认端口 7071）。
  - 前端：`.env.development` 中设置 `VITE_API_BASE`，关闭 mock 后访问 Sources/Analysis/Logs/Events。

## 运行环境（本会话）

- `cwd`: `D:\\Projects\\ai\\cv`
- 文件系统：`workspace-write`
- 网络：`restricted`
- 审批策略：`on-request`

## 结论摘录（便于快速对齐）

- “前端 web 除了 WHEP 应该只对接 control plane？”——需要（已确认）。
- “将两个后端项目重新构建一下？”——需要（执行时注意先停进程）。
- “我们是否继续按《核心流程修改.md》推进？”——需要（持续对齐）。
- 当前优先级：优先推进“VSM caps 扩展 + CP 透出”。

---
如需补充其它上下文（例如模型清单、图谱 requires 示例、真实 WHEP SDK 接入状态），可在本文件追加相应小节以保持信息同步。

