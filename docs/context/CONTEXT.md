# 项目上下文（2025‑11‑08｜VA + Triton 合容器｜CUDA/ORT/TRT）

本文基于当前对话全面重构：聚焦合容器部署、Triton 客户端接入、CUDA SHM 规范化与环境限制下的稳定策略。

## 1. 架构与数据流
- VA：RTSP → NVDEC/CUDA 预处理 → 推理（ORT CUDA/ORT‑TRT/原生 TRT/Triton gRPC）→ YOLO 后处理（GPU/CPU）→ CUDA 叠加 → NVENC → WHEP。
- Triton：同容器运行（HTTP:8000/gRPC:8001/Metrics:8002），模型仓库 `/models`（挂载 `docker/model`）。

## 2. 关键改动（本轮）
- 启用 Triton C++ 客户端：构建期 `-DUSE_TRITON_CLIENT=ON`，从 `tritonserver:25.08-py3-sdk` 引入 `grpc_client.h/libgrpcclient.so`，运行期注入 `/opt/tritonclient/lib`。
- 合容器运行：`entrypoint.sh` 先起 Triton 并轮询 Ready(HTTP 200)，再启动 VA，避免 *connection refused*。
- CUDA SHM 规范化：
  - 仅对 `cudaMalloc` 的 device 指针注册；复制用 `cudaMemcpyD2D`；
  - 在 `cudaMalloc / cudaIpcGetMemHandle / cudaMemcpy` 前固定 `cudaSetDevice(opt.device_id)`；
  - 输出端注册前以 `cudaPointerGetAttributes` 校正 `device_id`；
  - 会话互斥；析构时反注册输入与所有输出 SHM；失败本帧退回 Host，后续持续重试（不自动关闭 SHM）。
- 设备映射/IPC：Compose 以 GPU UUID 绑定同一物理卡（容器内 `CUDA_VISIBLE_DEVICES=0`），两服务 `ipc: host`。

## 3. 构建与缓存
- ORT 1.23.2（`CMAKE_CUDA_ARCHITECTURES=120`），`NGC_TRT_TAG=25.08-py3`；ORT 层以 `/opt/onnxruntime/.build.tag` 控制复用，源码改动不触发重建；可用 `ORT_REBUILD=1` 强制重建。

## 4. 运行与配置
- 端口：VA 8082/9090/50051；Triton 8000/8001/8002。
- app.yaml：
  - `engine: { type: triton, provider: triton, device: 0 }`
  - `options.triton_url: localhost:8001`（合容器）
  - `options.triton_model: yolov12x`；`triton_input: images`；`triton_outputs: output0`
  - 可选 SHM：`triton_shm_cuda: true`、`triton_shm_outputs: true`（环境不支持时自动按帧回退 Host）
- 模型 `config.pbtxt`：`tensorrt_plan`，input `images[3,640,640]`，output `output0[84,8400]`，`instance_group{gpus:[0]}`。

## 5. 现状与结论（Triton + CUDA SHM）
- 同容器 + UUID 绑定 + 设备防守后，仍可能在 WSL2/Docker Desktop 下出现服务器端 `invalid device context/invalid resource handle`（宿主限制）。
- 本实现坚持“SHM 常开、失败本帧回退 Host、后续重试”，保证业务稳定；在纯 Linux 宿主上通常可获得成功的 CUDA IPC。

## 6. 快速排障
- Triton Ready：`curl http://127.0.0.1:8000/v2/health/ready` ⇒ 200。
- I/O 名：`curl http://127.0.0.1:8000/v2/models/yolov12x/config`。
- 设备核对：容器内 `echo $NVIDIA_VISIBLE_DEVICES; nvidia-smi -L`（UUID 与 ordinal=0 一致）。
- 常见报错：
  - `connection refused` → 需等待 `ready` 再启动 VA（已修复于 entrypoint）。
  - `invalid device context/resource handle` → 环境限制；确认 UUID/IPC/setDevice/attrs，必要时在纯 Linux 验证。

## 7. 建议
- 若必须启用 CUDA SHM，请在纯 Linux 宿主验证；否则保留当前策略（SHM 常开 + Host 兜底）即可交付。
- 可引入 `VA_TRITON_SHM_DEBUG` 开关，失败时打印指针属性与注册 device_id 以供现场定位。
