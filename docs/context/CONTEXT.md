# 项目关键上下文（截至当前会话）

## 背景与目标
- 项目包含 VA（video-analyzer）、CP（controlplane）、VSM 三模块，前端通过 CP 控制，CP/VA/VSM 之间 gRPC 通讯。
- 近期目标：
  1) 彻底修复 GPU 零拷贝推理（NVDEC→预处理→ORT→后处理→NVENC/渲染）路径的 IoBinding/同步问题。
  2) 解决 CP 订阅接口的 504 和“状态长期 pending”问题，保证端到端订阅可达 ready。
  3) 设计无轮询的事件通知（SSE）。

## 发现的问题与现象（初始）
- VA 日志：`provider=cpu gpu_active=false io_binding=false`；`ms.node_model out_count=0`；`Graph node failed: nms`；未见 `pp.yolo` 日志。
- 推断：未启用 USE_ONNXRUNTIME 或 ORT CUDA EP 未附加，GPU 张量传入 NMS 导致失败。
- CP 侧：`POST /api/subscriptions` 返回 504（TIMEOUT）。

## 修复与实现（VA）
1) 启用 USE_ONNXRUNTIME 并确保运行时 DLL：
   - 使用本地 5090D 支持的 ORT 构建：`third_party/build/onnxruntime/build/Windows/Release/Release/onnxruntime*.{dll,lib}`。
   - 链接与复制到 `video-analyzer/build-ninja/bin`。
2) 统一 ORT 计算流（首选方案，CUDA EP V2）：
   - 文件：`video-analyzer/src/analyzer/ort_session.cpp`。
   - 通过 `SessionOptionsAppendExecutionProvider_CUDA_V2` 设置：`device_id`、`do_copy_in_default_stream=0`、`user_compute_stream=<TLS 流>`。
   - IoBinding 输入：H2D/D2D 使用 `cudaMemcpyAsync(..., ort_stream)`；避免外部 device 指针直绑，保证可见性与顺序。
   - 修正 V2 选项构造的 key/value 容器容量，避免“key/value cannot be empty”导致回退到旧 EP。
3) 推理解诊日志：新增 `analyzer.ort/ort.run.in/ort.run.bind/ort.run`，并在 `ms.node_model`、`ms.nms`、`pp.yolo` 打点。
4) 验证结果：
   - 看到 `provider=cuda io_bind=true dev_bind=true`。
   - 输出形状 `1x84x8400`，`ms.node_model out_count=1`，后处理正常（无目标时 `boxes=0`）。

## 修复与实现（CP）
1) 504 超时根因：`va_subscribe` 将 SubscribePipeline 截断为 ~1.5s deadline。
   - 文件：`controlplane/src/server/grpc_clients.cpp` 修复为使用配置超时 `va.timeout_ms`（默认 30000ms）。
2) pending 不变问题：GET `/api/subscriptions/{id}` 仅回 Store 的 phase。
   - 文件：`controlplane/src/server/main.cpp` 新增基于 VA `ListPipelines` 的运行时推断：如 `running=true` → 返回 `ready`。
3) 验证结果：
   - `POST /api/subscriptions` 返回 202 + Location。
   - `GET /api/subscriptions/{id}` 可见 `phase=ready`。

## 仍待事项 / 设计（SSE 无轮询）
- 新增 SSE：`GET /api/subscriptions/{id}/events`（server-sent events）
  - 由 `controlplane/src/server/main.cpp` 路由到 `try_start_va_watch(...)`。
  - `watch_adapter.cpp` 已实现从 VA 的 Watch(gRPC) 透传 `phase` 事件（含 keepalive/idle）。
  - 事件格式：`event: phase` + `data: {id,ts_ms,phase,reason}`，终态（ready/failed/cancelled）后关闭。

## 触达与分支
- 所有修复推送到 `IOBinding` 分支。
- 关键改动文件：
  - VA：`src/analyzer/ort_session.cpp`、`src/core/pipeline_builder.cpp`（汇总日志）、`docs/memo/2025-10-29.md`。
  - CP：`src/server/grpc_clients.cpp`、`src/server/main.cpp`、`src/server/watch_adapter.cpp`（已有）。

## 测试方式（现行）
- 后端：
  - 启动 VA：`VideoAnalyzer.exe build-ninja/bin/config`。
  - RTSP：`rtsp://127.0.0.1:8554/camera_01`。
  - 观察 `logs/video-analyzer-release.log` 的 `ort.run*`、`ms.node_model`、`pp.yolo`、`ms.nms`。
- CP：
  - `POST /api/subscriptions?use_existing=0` → 202 + Location。
  - `GET /api/subscriptions/{id}` → 期望 `phase=ready`。
  -（后续）`GET /api/subscriptions/{id}/events` → SSE 事件流。

## 风险与注意
- ORT CUDA EP V2 选项必须保证 key/value 指针有效期。
- 运行时 DLL 与驱动版本需兼容（5090D）。
- CP 与 VA 的 TLS 证书路径一致；gRPC 超时/重试须合理。

