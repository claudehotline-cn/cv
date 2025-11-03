# 项目上下文（2025-11-03 更新，VA/CP/VSM/Web + Docker）

本文件聚焦当前会话中的关键结论、配置变更与问题定位，覆盖：GPU 零拷贝路径（IoBinding/CUDA）、Docker 构建（ORT 源码编译）、模型/图配置、CP 交互与最小验证流程。

## 架构与数据流
- VA：RTSP 拉流 → 预处理（NVDEC→CUDA Letterbox）→ 推理（ONNX Runtime CUDA/TensorRT）→ 后处理（YOLO NMS，CPU/GPU 可选）→ 叠加与编码（NVENC）→ WebRTC（WHEP）。
- CP：对外 REST；编排订阅（/api/subscriptions），代理 WHEP；提供 /api/control/pipeline_mode、/api/control/hotswap 等控制路径。
- VSM：RTSP 源管理（可选）。
- Web：通过 CP 与 VA 交互。

## Docker 与构建（GPU）
- Dockerfile.gpu：
  - 运行时基础镜像：`nvidia/cuda:<ver>-cudnn-runtime-ubuntu22.04`（保证 libcudnn 就绪）。
  - 从源码构建 ONNX Runtime v1.23.2：启用 CUDA，支持可选 TensorRT（探测到 NvInfer 头文件自动开启）。
  - CUDA 架构：统一使用 `CMAKE_CUDA_ARCHITECTURES="90;120"`（兼容 RTX 5090d）。
  - 构建产物安装到 `/opt/onnxruntime`，VA 以该路径编译链接。
- Compose（GPU override）：
  - 模型卷仅映射为相对路径友好的 `/app/models`；图/YAML 中统一写 `models/xxx.onnx`。
  - 日志：`/logs/video-analyzer-release.log` 映射宿主 `logs/`。

## 零拷贝路径与默认策略
- IoBinding：在 GPU Provider（cuda/trt）场景默认启用；VA 统一使用 TLS CUDA 流（user_compute_stream）。
- 预处理：在 GPU Provider 下默认选择 CUDA letterbox。
- 输出视图：`device_output_views=true`、`stage_device_outputs=false`，下游 GPU NMS 可直接消费设备张量。
- NMS：支持 CPU/GPU 两条；GPU NMS 用于零拷贝路径验证。

## 日志增强（用于精确定位）
- 加载阶段（analyzer.ort）：
  - provider_req/resolved、inputs/outputs、首个输入 dtype/shape。
  - I/O 名称摘要（前 8 个）。
  - 若 `outputs==0`：立即错误日志 `model has zero outputs (path=...)`。
- 运行阶段：
  - `ort.run.start`：provider、IoB 开关、dev_bind、输入形状与 on_gpu。
  - `ort.run`：`outputs` 与 `out0..2_shapes`、前两个输出 dtype。
  - `ms.node_model`：`out_count` 与前 3 个输出形状（含 gpu/cpu 标记）。

## 当前阻塞与结论
- 现网日志表明：`models/yolov12x.onnx`、`models/yolov12n.onnx` 在 ORT 会话中被识别为 `zero declared outputs`。这不是“检测框为 0”，而是“模型 Graph 未声明任何输出张量”。
- 仅当 det 产生 `det_raw`（至少一个模型输出张量）时，nms 才能工作；否则管线在 det 或 nms 节点失败。

## 模型要求与修复建议
- 使用“无 NMS 的 ONNX”，但必须具备 Graph 输出（head logits 等），且（如使用 external data）确保所有分片随同挂载至 `/app/models`。
- 替换为已知可用的小模型先通路（例：yolov8n.onnx，导出时 `nms=False`），确认 det_raw 产出 → 切回目标模型。
- 如需继续用“内置 NMS”的 onnx：应移除 graph 的 post.yolo.nms 节点，改为解析模型输出的自定义后处理，或改用 ORT TensorRT EP 并适配输出；此路线与“统一 CUDA 流零拷贝 + 可控阈值”的既定设计不一致，不推荐。

## CP 交互（最小流程）
- 订阅：`POST /api/subscriptions?stream_id=camera_01&profile=det_720p&source_uri=rtsp://host.docker.internal:8554/camera_01` → 返回 202 + Location。
- 切换实时/暂停：`POST /api/control/pipeline_mode`（analysis_enabled true/false）。
- 热更新模型：`/api/control/hotswap`（要求 pipeline_name/node/model_uri，CP 转发至 VA gRPC）。

## 验证与指标
- 日志：`analyzer.ort load` / `ort.run.start` / `ort.run` / `ms.node_model`。
- 指标：`va_d2d_nv12_frames_total`、`va_overlay_nv12_passthrough_total` 递增验证零拷贝链路。

## 现状与下一步
- 已落地：IoBinding/CUDA 预处理默认开启；Dockerfile.gpu 改为 ORT 源码构建；日志增强；模型/卷统一相对路径；NMS 改回 GPU 验证。
- 待完成：提供“有 Graph 输出”的 onnx；观测新日志字段；若需 TRT EP，确保容器内 TRT dev 依赖与 ORT TRT 编译启用。
