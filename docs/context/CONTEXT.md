# 项目上下文与关键信息（重建）

本文整合当前对话与代码库现状，覆盖架构/路由、数据库、WHEP 代理、前端联调、GPU 零拷贝与检测框问题、构建运行与风险。时间：2025-10-31。

## 1. 目标与范围
- 目标
  - 使用 Chrome DevTools 调试前端“分析”页，确保经 CP 代理 VA 的 WHEP 协商稳定可用并播放。
  - 在 CP 实现并打通 DB 驱动的只读接口：`GET /api/models`、`GET /api/pipelines`、`GET /api/graphs`。
- 模块与交互
  - CP（controlplane）向前端提供 REST/代理；与 VA（video-analyzer）、VSM（video-source-manager）通过 gRPC/HTTP 协作；对外代理 WHEP。
  - 前端（web-frontend）仅访问 CP；开发态使用 Vite 代理统一到 CP 以避免 CORS。
  - VA 负责 RTSP 接入、推理、后处理与 WebRTC/HLS 输出；Watch 事件映射为 CP 的 SSE。
  - VSM 负责 RTSP 源管理。

## 2. 已完成与现状
- CP 构建：`tools/build_controlplane_with_vcvars.cmd` 已可生成 `controlplane/build/bin/controlplane.exe`。
- 路由与代理
  - 列表接口：`/api/models|/pipelines|/graphs` 读取 MySQL（Classic 优先，ODBC/X 备选），失败时空数组兜底；提供 `/api/_debug/db` 返回最近一次 SQL 异常与配置快照用于排障。
  - CORS/预检：统一处理 `OPTIONS`，暴露必要头。
  - WHEP 代理：强制 `Accept: application/sdp`（仅 POST），`Accept-Encoding: identity`，透传 `Authorization/Content-Type/If-Match`；支持 chunked 去分块；重写 `Location` 到 CP 路径并 `Access-Control-Expose-Headers` 包含 `Location/ETag/Accept-Patch`。
  - 订阅：`POST /api/subscriptions` 返回 `{ code:"ACCEPTED", data:{ id:"..." } }`，前端读取 `data.id`；SSE `GET /api/subscriptions/{id}/events` 映射 VA Watch（现已可用，仍需长期跑稳定性验证）。
  - `/api/sources`：当 VSM 为空时可注入默认源 `camera_01` 的回退（开发态便利，生产可关闭）。
- 前端联调：Vite 将 `/api,/metrics,/whep` 代理到 `http://127.0.0.1:18080`，已删除直连 VA 的开发配置，默认使用 `det_720p`。

## 3. 数据库与依赖
- MySQL：`host=127.0.0.1 port=13306 user=root password=123456 db=cv_cp`（确认有数据：models=5/pipelines=4/graphs=3）。
- 连接器优先级：Classic（third_party/mysql-connector-c++-9.4.0-winx64）→ ODBC（需安装驱动）→ X DevAPI（需启用 X Plugin）。
- 运行时 DLL：`mysqlcppconn-10-vs14.dll`、`libssl-3-x64.dll`、`libcrypto-3-x64.dll` 等，如缺可从 `video-analyzer/build-ninja/bin` 复制至 CP 运行目录。
- 常见问题：`caching_sha2_password`/RSA 公钥获取、SSL 模式、DLL 缺失；均会在 `/api/_debug/db` 中暴露最近异常文本。

## 4. WHEP 时序与验证要点
1) `POST /api/subscriptions` → 202 + `data.id`
2) `GET /api/subscriptions/{id}/events` → `phase=ready`
3) `POST /whep` → 201 + `Location`（CP 相对路径）
4) `PATCH <Location>`（ICE）→ 204/2xx，随后 `<video>` 触发 `loadedmetadata/playing`
注意：必须强制 `Accept: application/sdp` 与 `identity` 编码；请求体按 `Content-Length` 全量读取，避免截断。

## 5. 检测框问题与 GPU 路径
- 分支：`IOBinding`。为零拷贝路径统一 CUDA stream，修正 IoBinding dtype（F16/F32）与 FP16 主机转换兜底；CUDA 预处理/解码/NMS/叠加均接受同一 stream，避免跨线程 TLS 竞态导致框漂移。
- 仍在推进：设备侧 `half_to_float` + 纯设备解码；可选恢复“每流水线独立非阻塞流”以提升并行度（先以稳定为先）。
- 曾出现的日志与回退：删除 `infer: in_key='tensor:det_input' shape=1x3x640x640 on_gpu=true` 噪声日志；对 yolo 解码核的接口扩展如不匹配需局部回退，确保可编译可运行。

## 6. 构建、运行与测试
- 构建前先停止正在运行的 CP/VA/VSM（可用 `tools/kill_running.ps1`）。
- Windows 构建脚本：
  - CP：`tools/build_controlplane_with_vcvars.cmd`
  - VA：`tools/build_va_with_vcvars.cmd`（输出在 `video-analyzer/build-ninja`）
  - VSM：`tools/build_vsm_with_vcvars.cmd`
- 运行：
  - VA：`video-analyzer/build-ninja/bin/VideoAnalyzer.exe .../config`
  - VSM：`video-source-manager/build/bin/VideoSourceManager.exe`
  - 前端：`web-front` 下 `npm run dev`
- 验证：端口可达、3 个 DB 列表接口非空、订阅→SSE→WHEP 全链路、画框正确；测试源 `rtsp://127.0.0.1:8554/camera_01`。

## 7. 已知风险与对策
- DB 认证/依赖缺失 → `/api/_debug/db` 快速暴露；按需切换 ODBC/X。
- 代理细节（Accept/Location/Chunked） → CP 已内建兜底；保留最小充分日志。
- SSE 长连稳定性 → 增加可靠性重试与限流；先以可观测为主。
- GPU 设备侧 FP16 改造 → 分阶段上线，优先保证几何一致性；回退路径保留。
- VSM 为空导致前端列表空 → 开发态默认源兜底，生产关闭。

