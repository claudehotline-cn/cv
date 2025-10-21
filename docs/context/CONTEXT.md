# 项目上下文（自动生成）

本文汇总本仓库当前对话与实现进展的关键上下文，便于统一认知、规划与验证。

## 范围与目标
- 目标：以“异步订阅 + SSE（Server-Sent Events）进度流”替代旧轮询/旧按钮链路；前端展示阶段化进度条；端到端（VA/VSM/前端）在本地可构建、可运行、可测试。
- 不使用临时 `stream_id`；统一新接口与状态机；确保回退策略与可观测性。

## 模块与通信
- VA（video-analyzer）：RTSP 接入、推理、后处理、WebRTC/HLS 输出；新增异步订阅与 SSE 事件流。
- CP（control_plane_embedded，位于 `video-analyzer/src/control_plane_embedded`）：与 VA/VSM 通过 gRPC；前端仅与 CP/网关交互（现阶段仍内嵌在 VA 工程）。
- VSM（video-source-manager）：管理 RTSP 源；gRPC: `7070`，REST: `7071`。
- 前端（web-frontend）：以 `createSubscription + SSE` 统一 Start/Stop/Detach 等分析操作；分析面板显示阶段进度条与终态错误。

## 关键接口与状态
- 订阅 REST：`POST/GET/DELETE /api/subscriptions`。
- 事件流 SSE：`GET /api/subscriptions/:id/events`（阶段、百分比、错误聚合）。
- 指标：暴露订阅队列、状态分布、完成计数、时长直方图等 `/metrics`（Prometheus/Grafana）。
- 前端状态机：仅在 SSE ready 后置 `analyzing=true`；只在终态显示错误；支持取消（stop/cancel）。

## 已完成功能（对话纪要）
- VA：异步订阅全链路与 SSE 事件流落地；修复 `handleSubscriptionGet` 缺少 `payload.data`；指标已接入。
- VSM：`/api/source/add|list` 可用；VA `/api/sources` 聚合可见；推流源示例：`rtsp://127.0.0.1:8554/camera_01`。
- 前端：
  - store（`web-front/src/stores/analysis.ts`）改为 `createSubscription + SSE`；
  - `Sources.vue`、`Pipelines.vue`、`Sources/List.vue` 统一调用 `store.startAnalysis/stopAnalysis`；
  - `AnalysisPanel.vue` 增加进度条与错误显示收敛；WHEP 播放可见（`presentedFrames` 持续增长）。
- 测试：本地构建运行与基于页面操作的 Playwright 验证通过（含 RTSP 源）。

## 仍待事项（优先级）
1) 文档：重建本文件与 `ROADMAP.md`（本次已执行）。
2) 前端：
   - 在分析面板加入“取消”按钮并调用 `store.stopAnalysis`；
   - 将 VSM phase（Ready/Unknown）与 UI 状态映射一致；
   - SSE 断线重连与回退轮询策略（现仅一次 2.5s 兜底）。
3) 测试：
   - Playwright 场景化用例：
     - 列表启动 → 分析页进度 → Ready → 播放；
     - 订阅后立即取消 → `cancelled`；
     - 错误 RTSP → 失败原因可见；
   - 后端异常路径：订阅超时、模型加载失败、取消竞争；
   - 并发稳定性与长时间 SSE 稳定性。
4) 观测：提供 Grafana 面板 JSON 与告警阈值（时延、失败率、队列长度）。
5) 仓库清理与远端一致性：确认异常文件清理、分支推送一致。

## 环境与运行（Windows 优先）
- 构建脚本：`D:\Projects\ai\cv\tools\build_va_with_vcvars.cmd`（VA），VSM 在其 `build` 目录；Linux/macOS：`cmake -S . -B build && cmake --build build -j`。
- 运行顺序：
  1) 启动 VSM（gRPC:7070 / REST:7071），
  2) 启动 VA：`video-analyzer\build-ninja\bin\VideoAnalyzer.exe ...\config`，
  3) 前端：在 `web-front` 设置 `VITE_API_BASE=http://127.0.0.1:8082` 后 `npm run dev`。
- 推流：`rtsp://127.0.0.1:8554/camera_01`（确保 mediamtx/ffmpeg 正在推流）。

## 测试规范与工具
- 后端：构建成功后必须测试；脚本放置于 `video-analyzer/test/scripts`；最低要求“处理帧数 > 0 且无 HTTP/RTSP 错误”；建议断言 FPS/检测数量。
- 前端：使用 Playwright/Chrome DevTools MCP；严格遵守“最小充分”取证与输出约束；WHEP 可参考 `chrome://webrtc-internals/`。
- 数据库校验：`C:\Program Files\MySQL\MySQL Shell 8.4\bin\mysqlsh.exe`。

## 已知问题与注意
- 旧控制平面/旧 `/api/subscribe|unsubscribe` 路径须移除或封禁，防止混用。
- `AnalysisPanel.vue` 曾出现 PostCSS `Unknown word \\`r\`n` 报错，需排查样式块中意外字符或换行符编码（CRLF→LF）、多余分隔符。
- 严格“不要使用临时 stream_id”，统一以服务端订阅 ID 与资源标识驱动状态机。

## 设计与规范（摘要）
- 设计原则：开闭/里氏/依赖倒置/单一职责；新增 GPU 路径需保留 CPU 回退并以开关保护。
- C++ 风格：`snake_case` 函数/文件，类 `CamelCase`；合理使用 `const`、`std::span`、`std::string_view`、智能指针；与周边格式一致。
- 文档制图：如需图示，采用 Mermaid。

