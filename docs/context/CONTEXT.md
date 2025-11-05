# 项目上下文（2025-11-04 更新，VA/CP/VSM/Web + Docker + TensorRT）

本文件聚焦当前会话的关键决定、变更与问题定位：GPU 零拷贝路径、Docker 内 ORT 源码编译（SM=90;120）、前端提示修复、以及 TensorRT/RTX 引擎设计与实施路线。

## 架构与数据流
- VA：RTSP 拉流 → 预处理（NVDEC→CUDA Letterbox）→ 推理（ONNX Runtime CUDA/TensorRT）→ 后处理（YOLO NMS，CPU/GPU 可选）→ 叠加与编码（NVENC）→ WebRTC（WHEP）。
- CP：对外 REST；编排订阅（/api/subscriptions），代理 WHEP；提供 /api/control/pipeline_mode、/api/control/hotswap 等控制路径。
- VSM：RTSP 源管理（可选）。
- Web：通过 CP 与 VA 交互。

## Docker 与构建（GPU）
- Build 基镜像：`nvidia/cuda:<ver>-cudnn-devel-ubuntu22.04`；Runtime 基镜像：`cudnn-runtime`。
- 容器内源码构建 ORT v1.23.2：`CMAKE_CUDA_ARCHITECTURES="90;120"`，禁用 Flash-Attention，并行 24；`--allow_running_as_root`。
- 安装到 `/opt/onnxruntime`，并补全 `libonnxruntime.so/.so.1` 链接；`LD_LIBRARY_PATH` 包含该目录。
- 修复：在 build 阶段重新声明 `ARG CUDA_VER` 以消除 `${CUDA_VER%.*}` 报错；确保链接到我们构建的 ORT（此前未链接导致 `zero declared outputs` 误判）。
- Compose：模型卷映射到 `/app/models`；图 YAML 统一写 `models/xxx.onnx`；日志映射到宿主 `logs/`。

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
- 之前的 `zero declared outputs` 根因是运行时未正确装载我们编译的 ORT；已通过容器内编译与链接修复。容器内 Python 校验脚本 `/app/tools/check_onnx.py` 已验证模型 `yolov12n/x.onnx` 均能输出 `[1,84,8400]`。

## 模型与 NMS
- 模型需“无内置 NMS 且有 Graph 输出”；如有 external data，需一并挂载到 `/app/models`。
- NMS：默认使用 GPU 分支；阈值保持 `conf=0.65, iou=0.45`（按需求）。

## CP 交互（最小流程）
- 订阅：`POST /api/subscriptions?stream_id=camera_01&profile=det_720p&source_uri=rtsp://host.docker.internal:8554/camera_01` → 返回 202 + Location。
- 切换实时/暂停：`POST /api/control/pipeline_mode`（analysis_enabled true/false）。
- 热更新模型：`/api/control/hotswap`（要求 pipeline_name/node/model_uri，CP 转发至 VA gRPC）。

## 验证与指标
- 日志：`analyzer.ort load/ort.run` 或后续 `analyzer.trt load/trt.run`、`ms.node_model out_count`。
- 指标：`va_d2d_nv12_frames_total`、`va_overlay_nv12_passthrough_total` 递增。

## 前端修复
- 分析页面“实时分析”提示乱码：`AnalysisPanel.vue` 已改为中文 `'已开始实时分析'`，构建后生效。

## TensorRT 引擎路线（5090D / SM_120）
- Provider 选择（优先→回退）：`tensorrt-rtx` → `tensorrt` → `cuda`；阶段二新增 `tensorrt-native`（原生 TRT 会话）。
- 新增工厂 `model_session_factory`，NodeModel 依赖抽象与工厂（不改 YAML）。
- 满足 SOLID：SRP/ISP（职责内聚）、OCP/DIP（新增 Provider 无需改调用方）、LSP（会话可替换）。
- 设计文档：`docs/design/tensorrt_engine.md`（已提交）。

## 现状与下一步
- 已落地：IoBinding/CUDA 预处理默认开启；Dockerfile.gpu 改为 ORT 源码构建；日志增强；模型/卷统一相对路径；NMS 改回 GPU 验证。
- 待完成：提供“有 Graph 输出”的 onnx；观测新日志字段；若需 TRT EP，确保容器内 TRT dev 依赖与 ORT TRT 编译启用。
