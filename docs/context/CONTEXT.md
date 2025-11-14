# CONTEXT（2025-11-14）

本文件梳理当前对话中围绕“训练流水线 + 模型仓库 + VA 视频输出画质调优”的关键结论，作为 M0–M2 规划与日后调试的基线上下文。

---

## 一、系统角色与职责边界（回顾）

- **video-analyzer（VA）**
  - 负责推理运行时与多阶段分析：RTSP 解码（FFmpeg / NVDEC）、预处理、Triton In-Process 推理、后处理（NMS）、CUDA/CPU overlay。
  - 输出路径：
    - WebRTC DataChannel（兼容旧 Web 端）。
    - WHEP（WebRTC-HTTP Egress）下行 H.264 轨，供 Web 前端 `WhepPlayer` 播放。
  - 模型仓库：通过 Triton In-Process + S3/本地文件系统管理 TensorRT plan。

- **controlplane（CP）**
  - REST API 网关 + 编排层：负责训练代理、模型一键部署、灰度/别名管理、VA 控制。
  - 提供：
    - `/api/train/*`：训练作业启动、状态、工件查询。
    - `/api/train/deploy`：一键部署（accuracy / size_mb 门槛，S3 优先拉取）。
    - `/api/control/pipeline_mode`：切换 per-stream 分析模式（分析 / 原始）。
    - `/whep`：反向代理 VA 的 WHEP 端点，处理 CORS 与 Location 重写。

- **model-trainer（Trainer）**
  - FastAPI 服务，负责分类任务训练、MLflow 集成与工件产出。
  - 产出标准工件：`model.onnx` + `model.yaml`，可上传至 MinIO。

- **web-front**
  - Vue + Element Plus SPA。
  - 训练页 `/training`：表单化配置 + SSE 监控。
  - 分析面板：通过 `WhepPlayer` 播放分析后视频流，`useAnalysisStore` 统一管理 source/pipeline/graph/model 状态，并通过 CP 控制分析开关。

- **基础设施**
  - MySQL：`cv_cp` 库，CP 训练作业与配置存储。
  - MLflow + MinIO：训练 Run 及工件的追踪与存储（S3 Artifact Store）。
  - Docker Compose：统一拉起 mysql/minio/mlflow/trainer/va/cp/web/vsm。

---

## 二、视频分析与 WHEP 播放链路

1. **订阅与 Pipeline 构建**
   - 前端在 Pipelines 分析面板通过 `createSubscription` 创建订阅：
     - `stream_id`：如 `camera_01`。
     - `profile`：如 `det_720p`。
     - CP 使用 restream 基址为 VA 拼接 RTSP 源 URI。
   - VA 内部 `TrackManager` + `PipelineBuilder` 创建 pipeline：
     - 解码源（NVDEC/FFmpeg）。
     - 多阶段 graph（`analyzer_multistage_example`）：`pre → det → nms → ovl`。
     - 编码器（FFmpeg H.264 / NVENC）。
     - WebRTCDataChannel + WhepSessionManager 推流。

2. **WHEP 交互**
   - 前端 `WhepPlayer`：
     - 构造 `RTCPeerConnection` + recvonly video transceiver，偏好 H.264 `packetization-mode=1`。
     - 调用 CP `/whep`：
       - `POST /whep?stream=<stream_id:profile>&variant=overlay` 发送 Offer SDP，获取 Answer SDP 与会话 Location。
       - `PATCH` 发送 ICE 候选与结束标记。
   - CP 将 `/whep` 请求转发到 VA REST，VA 内部 `WhepSessionManager` 基于 libdatachannel 建立 H.264 sendonly 轨，并通过 `feedFrame` 接受编码后 Annex-B H.264。

3. **分析模式切换**
   - 前端在分析面板通过 `setPipelineMode(stream_id, profile, analysis_enabled)` 控制：
     - `true`：pipeline 进入“分析 + overlay”模式；
     - `false`：同一 key 下仅编码原始帧（raw passthrough），供对比与暂停。
   - VA `Pipeline::setAnalysisEnabled` 内部切换分支，并请求下一帧 IDR 以避免切换瞬间伪影。

---

## 三、编码链路与画质问题定位

本次对话的核心是“有检测框，但前端播放画面发糊、有噪点”，看起来像编码或解码不佳。

1. **初始问题与根因**
   - 早期逻辑中，当 profile 未显式设置 `encoder.codec` 时，`Application::buildEncoderConfig` 默认回退为 `jpeg`，与 WHEP/H.264 路径不匹配，存在潜在比特流错配风险。
   - Docker 部署中 profile 的编码码率仅为 3500kbps（1280×720@30），对复杂监控场景而言主观画质偏糙、噪点明显。
   - NVENC 默认 `rc=cbr` 且关闭空间/时间 AQ，进一步放大颗粒感。
   - H.264 SPS/PPS 注入逻辑存在顺序 bug：先判断 `out_packet.keyframe` 再赋值，导致关键帧前不会重复注入参数集，重连/切流时解码更敏感。

2. **代码层修复**
   - `video-analyzer/src/app/application.cpp`
     - 默认 codec 改为 `h264`，仅在配置显式声明时启用 `jpeg`，确保 WHEP/H.264 路径统一。
   - `video-analyzer/src/media/encoder_h264_ffmpeg.cpp`
     - SPS/PPS 注入修复：先依据 `AV_PKT_FLAG_KEY` 设置 `out_packet.keyframe`，再判断是否拼接 `spspps_annexb_`，确保每个 IDR 都携带完整参数集。
     - NVENC 码控调整：
       - 默认 `rc=cbr_hq`，开启 `spatial_aq=1`、`temporal_aq=1`，默认 `aq-strength=8`。
       - 通过环境变量 `VA_NVENC_RC/VA_NVENC_SPAQ/VA_NVENC_TAQ/VA_NVENC_AQ_STRENGTH` 允许覆盖。

3. **部署配置与调优（docker）**
   - `docker/config/va/profiles.yaml`
     - `det_720p` / `seg_720p`：
       - 分辨率：1280×720@30。
       - 码率：从 3500 → 8000 → 10000 kbps 逐步拉升，主观画质明显改善。
   - `docker/config/va/app.yaml`
     - `overlay_alpha` 从 0.25 调低到 0.15，减少大面积填充带来的“脏感”，保留清晰边框。
   - `docker/compose/docker-compose.yml`
     - `va` 服务挂载 `docker/config/va`，通过 `docker compose restart va` 应用新配置。
   - 运行日志确认：
     - `[Encoder][nvenc] mapped preset=p3 rc=cbr_hq sp_aq=1 tm_aq=1 ...`
     - `[Encoder] open OK codec='h264_nvenc' 1280x720@30 pix_fmt=NV12 bitrate_kbps=8000/10000`

4. **效果与结论**
   - 用户在分析面板确认：在 8Mbps 起画面已经“明显好很多”，10Mbps + 降低 overlay 透明度后进一步接近“源级流”主观清晰度。
   - 画质问题主要归因于重编码配置（码率/AQ/overlay），而非解码错误或轨道错配；当前编码链路可作为后续调优基线。

---

## 四、后续演进与约束

- 画质与性能权衡：
  - 720p 建议码率区间：8–10Mbps；如需 1080p 可按比例提升。
  - 可按 profile 维度分别调节码率与分辨率，结合 GPU/带宽做分级策略。

- WHEP 与前端协同：
  - 保持 `variant=overlay` 路径稳定，对 raw 需求采用 `pipeline_mode=false` + 同 key 推流策略。
  - 前端 `WhepPlayer` 继续收集 WebRTC stats（fps/framesDecoded/framesDropped）作为画质与抖动的观测信号。

- 兼容性与可观测：
  - 保持 `encoder.ffmpeg` 与 `transport.webrtc` 日志为 debug 级，便于线上快速定位编码/传输问题。
  - Grafana 面板中建议新增编码器相关指标：实际输出码率、NVENC RC/AQ 配置命中率、帧丢弃率等。***
