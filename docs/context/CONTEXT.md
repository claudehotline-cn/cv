# 当前对话关键上下文（VA/VSM、WHEP、DB 与前端分析页）

- 运行与端口
  - VA(REST): 127.0.0.1:8082；VSM(REST): 127.0.0.1:7071；VSM(gRPC): 127.0.0.1:7070。
  - MySQL: 127.0.0.1:13306，数据库 cv_cp。
- 协议与路由
  - WHEP（浏览器下行）：POST /whep?stream=stream:profile → 201 + Location；PATCH/DELETE /whep/sessions/:sid。
  - 控制面（CP）内嵌于 VA；VSM↔VA 编排走 gRPC，WHEP 可经 CP→VA gRPC 路由（VA_GRPC_HOSTS）。
  - 已清理 VA_GRPC_HOSTS 干扰，WHEP 201/Location/Answer 取证通过（answer≈6100 字节）。
- DB-only 读取
  - 日志/事件/会话：/api/logs、/api/events/recent、/api/sessions 已切为 DB-only，失败 503。
  - 分析图：/api/graphs 已从“枚举 YAML 目录”改为“DB-only（graphs 表）”。
- 前端改动
  - 路由：仅保留 /analysis（移除 /pipelines/analysis）。
  - 侧栏：新增“分析”顶层入口；Observability 下补 Sessions。
  - 分析页（/analysis）：
    - 下拉：Sources/Graphs 由接口填充（sources 来自 VSM 聚合 + VA，graphs 来自 DB）。
    - 播放：WhepPlayer 非 trickle，一次性 SDP，失败重试指数回退。
    - 订阅：startAnalysis 失败（400）时兜底一次（profile=det_720p、graph=analyzer_multistage_example、从 sources 补 uri），并避免 mock://whep 占位。
- 常见问题与修复
  - 订阅 400：多为 profile 为空/不合法或缺少 source_uri；已在前端兜底并指导使用 det_720p。
  - 分析图数量不一致：此前来自磁盘 YAML 扫描；现改为 DB-only 与数据库一致。
  - 扩展脚本报错（chrome-extension://invalid/）：来自浏览器扩展，非系统问题。
- 取证与健康
  - WHEP：201/Location/Answer 取证（docs/memo/assets/2025-10-18/whep_rtsp_cam01.json）。
  - VA/VSM 健康：/api/system/info、/api/source/list 分别 200。

## 使用与验证清单
- 启动：
  - VA：tools/win/restart_backend.ps1（8082 就绪）；VSM：VideoSourceManager.exe（7070/7071）。
- 订阅（后端直测）：
  - POST /api/subscribe { stream_id:"camera_01", profile:"det_720p", source_uri:"rtsp://127.0.0.1:8554/camera_01" } → 201。
- 前端 /analysis：
  - Pipeline 选 det_720p；视频源选 camera_01；分析图选 analyzer_multistage_example；自动播放开启。
  - 无画面时：点击“刷新”或切换一次“暂停/实时分析”。

## 待办与优先级
- 前端：
  - 在 UI 上显式展示订阅错误信息（含后端返回文案）。
  - /analysis 初次加载时，确保 sources/graphs 拉取失败可重试与提示。
- 后端：
  - /api/subscribe 返回更结构化的错误（缺失字段/非法 profile 的 code）。
  - /metrics 补 WHEP 会话、CP gRPC 计数/时延。
- 自动化取证：
  - Playwright 在 /analysis 切 det_720p + camera_01，等待首帧，保存 JSON 证据。

