# 项目上下文（VA/CP/VSM/Web + Docker）

本文汇总近期问题、修复与当前可运行形态，聚焦：容器化、模型与图配置、RTSP 拉流、CP 订阅与 SSE、WHEP/ICE 在纯内网的可达性，以及最小可验证路径。

## 架构与进程
- `video-analyzer`（VA）：拉 RTSP → 多阶段图（预处理/推理/后处理/渲染）→ 推送 WebRTC（WHEP）/ REST 控制。
- `controlplane`（CP）：对外 REST API 与订阅编排，向 VA 发起 gRPC/HTTP 控制，提供 `/api/subscriptions` 与 `/api/subscriptions/{id}/events`（SSE）。
- `video-source-manager`（VSM）：RTSP 源管理（可选）。
- `web-frontend`：分析页面（通过 CP API 交互）。

## 容器与配置要点
- 模型卷：将宿主 `docker/model` 映射到容器 `/models`，图文件中统一写绝对路径，例如：`/models/yolov12x.onnx`。
- 日志：容器内统一写 `/logs/video-analyzer-release.log`，宿主映射 `app/logs/` 目录。
- 数据库：CP 指向 `host.docker.internal:13306`（user: root / pwd: 123456 / db: cv_cp）。
- 证书：CP↔VA 双向 TLS，证书 SAN 统一（包含 `localhost`/内网 IP）；已验证 mTLS 互通。
- 依赖：容器构建期编译 `libdatachannel` 与 `IXWebSocket`，启用 WHEP；`ONNX Runtime` 已就绪（若需 GPU EP，请补齐匹配版本 cuDNN）。

## 关键配置片段
1) 图与模型（示例）
```yaml
# docker/config/va/graphs/analyzer_multistage_example.yaml
model_path: "/models/yolov12x.onnx"
profile: "det_720p"
```
2) 纯内网 WHEP/ICE（通过配置文件，不用环境变量）
```yaml
# docker/config/va/app.yaml
webrtc:
  ice:
    bind_address: "0.0.0.0"
    public_ip: "192.168.50.78"
    port_range_begin: 10000
    port_range_end: 10100
  mdns:
    disable: true
```
说明：
- 容器需映射 UDP 10000–10100；Windows 防火墙放行该范围。
- VA 将在 Answer SDP 的 `o=`/`c=` 与 `a=candidate` 中重写为 `public_ip`，浏览器候选即可直连。

## 订阅/播放最小链路
1) 创建订阅（CP）
```
POST http://127.0.0.1:18080/api/subscriptions?stream_id=camera_01&profile=det_720p&source_uri=rtsp://host.docker.internal:8554/camera_01
```
期望返回：202 + `Location: /api/subscriptions/{id}`。

2) 订阅事件（SSE）
```
GET /api/subscriptions/{id}/events
```
期望收到 `phase: ready` 等事件（已在 CP 实现/接好代理）。

3) WHEP 协商
- 前端向 CP 发起 WHEP Offer，CP/VA 返回 Answer；Answer 中应可见 `192.168.50.78` 的 host 候选。

## RTSP 拉流与冷启动
- VA 针对 FFmpeg/NVDEC 打开参数做了温和调优：`analyzeduration=1s`，`probesize=5MB`，支持低延迟开关（可选）。
- 冷启动超时：若大模型（如 `yolov12x`）首次加载超过 CP 超时，可在 `docker/config/cp/app.yaml` 提高 `va.timeout_ms`（如 60000），或先用小模型 `v8n` 验证链路。

## 已修复与变更
- ConfigLoader：YAML 判空与 `as<>` 防护，避免 Exit 139。
- WHEP 依赖：容器内构建 `libdatachannel` + `IXWebSocket`；VA `CMakeLists.txt` 检测并链接。
- CP SSE watch：实现 `/api/subscriptions/{id}/events`，能流式输出阶段事件与 VA 代理 Watch。
- 模型路径与卷：图文件改为 `/models/...`，compose 统一映射。
- TLS：CP↔VA 双向验证，证书 SAN 对齐。

## 已知事项与排查要点
- ORT CUDA EP 如需启用，需配套 libcudnn 对齐；否则回落 CPU。
- `/api/events/recent`：前端若调用该路由返回 404，可暂时隐藏 UI 或在 CP 侧补实现。
- 订阅超时：优先检查 VA 日志是否已连接 RTSP 并开始解码，确认 CP 超时设置与模型大小。

## 最小排查清单
- Docker：`docker ps` 确认 `va/cp/web/vsm` 状态；`docker logs <va>` 是否出现 RTSP 连接、解码与帧计数；`docker logs <cp>` 观察订阅超时/错误。
- DevTools：打开分析页，观察 Network 中 `/api/subscriptions` 与 `/whep` 请求，确认 Answer SDP 中 host 候选为 `192.168.50.78`。
- 端口：宿主 8554（RTSP）可达；容器 UDP 10000–10100 已映射；Windows 防火墙放行。

