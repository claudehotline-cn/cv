# 项目关键上下文（重建版）— 2025-11-01

本文件汇总当前对话期内的关键改动、现状、取证与后续方向，覆盖架构联调、WHEP 代理、订阅链路、数据库接口、前端代理、VA 推理与检测框修复（GPU/CPU）、以及阈值来源统一到图配置。

## 1. 架构与链路
- 前端仅连接 Controlplane（CP）；CP 通过 gRPC 调用 Video Analyzer（VA）与 VSM；CP 对外提供 REST 与 WHEP 反向代理。
- 分析播放链路：
  1) POST `/api/subscriptions` → 202 + Location + body.data.id
  2) 前端发起 WHEP：POST `/whep`（经 CP 代理）→ 201 + Location；随后 ICE PATCH（204）；<video> 播放。
- DEV 运行：前端 Vite 代理 `/api,/metrics,/whep → 127.0.0.1:18080`；VA(8082/50051)、VSM、CP(18080) 独立进程。

## 2. CP 改动与取证
- 订阅：修复 `source_uri` 未 URL 解码导致 VA 打开 `rtsp%3A…`。
- 响应：POST `/api/subscriptions` 统一 `{ code:"ACCEPTED", data:{ id } }` 并附 Location。
- HTTP 服务器：完整读取 Content-Length；状态行映射补全 201/204。
- WHEP 代理：强制 Accept=application/sdp；去分块；Location 暴露与重写；CORS 统一。
- 取证：
  - `/api/system/info` 200；`/api/models|/api/pipelines|/api/graphs` 均 200，长度 5/4/3。
  - POST `/api/subscriptions?...` → 202 + `Location: /api/subscriptions/cp-…` + body.data.id。
  - GET `/api/subscriptions/{id}/events` → 200 `text/event-stream`。

## 3. 前端改动与取证
- 开发态统一走 CP（相对路径 → Vite 代理），清理对 8082 的直连；页面硬刷新后生效。
- 分析页 WHEP：
  - Console/Network 可见：POST `/whep` 201 + ICE connected + `<video>` loadedmetadata/playing（1280x720）。

## 4. VA（推理/后处理/渲染）
- WHEP：VA REST `/whep` 正常创建会话（201），Answer SDP 返回；ICE PATCH/DELETE 可用。
- YOLO 后处理修复（GPU/CPU 一致）：
  - 类别分数自适应 sigmoid（logit→prob）；
  - 输出形状判定统一：`1x84x8400`→channels_first(C,N)，`1x8400x84`→(N,C)；
  - 归一化坐标放缩：按 normalized 判定使用 `pre_sx/pre_sy` 与 letterbox `scale/pad` 还原至原图；
  - CUDA 解码核与 CUDA NMS 使用相同阈值与放缩；
  - 诊断日志（节流）输出候选数与 NMS 结果。
- 阈值来源统一到图配置：
  - 图：`config/graphs/analyzer_multistage_example.yaml` post.yolo.nms 节点 `conf/iou`；
  - NodeNmsYolo 将阈值以方法参数注入后处理器（setThresholds），不再使用环境变量；
  - 默认阈值回退：conf=0.25、iou=0.45。
- 取证（示例）：
  - `ms.nms gpu_decode.pre … thr=0.65 ch_first=1 num_det=8400 num_attrs=84`；
  - `ms.nms gpu_decode candidates=118` → `ms.nms boxes=20` → `ms.overlay drawn boxes=20`。

## 5. 数据接口（DB）
- `GET /api/models|/api/pipelines|/api/graphs`：已稳定从 MySQL 读取（classic connector）。
- `_debug/db` 可用于捕获异常文本（开发辅助）。

## 6. 当前状态与结论
- 端到端（经 CP）播放稳定；订阅/WHEP/ICE 链路与日志齐全。
- 检测框几何恢复：GPU/CPU 路径阈值一致、坐标放缩一致；阈值来源改为图配置；日志可见候选与绘制数量。

## 7. 后续建议
- 将图配置阈值按业务场景回调（如 conf 0.25–0.35），观察 `boxes/drawn boxes` 与误报。
- 如需更干净日志，可提高 `VA_MS_LOG_LEVEL` 或加大节流时间；发布构建前关闭调试日志。

