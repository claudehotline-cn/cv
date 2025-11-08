# 项目上下文（2025‑11‑08｜VA ↔ Triton｜元数据自适配 + CUDA SHM + 指标）

本文梳理本轮对齐与落地：Triton gRPC 客户端集成、ModelMetadata 自适配、输入/输出 CUDA 共享内存、失败原因指标、构建链与文档。用于后续 ROADMAP 与测试复用。

## 架构与数据流
- VA：RTSP → NVDEC/CUDA 预处理 → 推理（优先序：tensorrt-native → triton → ORT-TRT → ORT-CUDA）→ NMS/后处理 → 叠加 → 编码/推流（WHEP）。
- Triton：HTTP:8000 / gRPC:8001 / Metrics:8002，模型仓库 `/models`（compose 挂载 `docker/model`）。

## 关键实现
- Provider 映射与回退链：NodeModel 支持 `force_provider`/`providers` 覆盖；自动按序回退，保障可用性。
- 元数据自适配：若可用 `grpc_service.pb.h`，加载时拉取 ModelMetadata，自动填充 input/output 名称；批次维异常时自动改用/移除 batch=1 重试一次。
- CUDA SHM：
  - 输入：稳定设备缓冲（cudaMalloc）→ cudaIpcGetMemHandle → RegisterCudaSharedMemory（容量变化重注）→ 每帧 D2D → Infer 前 SetSharedMemory 绑定；多次失败仅禁用“输入侧”SHM。
  - 输出：每个输出稳定设备缓冲 + 独立 SHM 名；Infer 后若容量满足，直接返回 device TensorView（on_gpu=true），否则回退 Host RawData。多次失败仅禁用“输出侧”。
  - 设备号映射：支持 `shm_server_device_id`，用于 Triton 容器与本进程 CUDA 设备序号不一致时的注册设备号对齐。
- 可观测性：
  - 指标：`va_triton_rpc_seconds`、`va_triton_rpc_failed_total{reason=…}`（create/invalid_input/mk_input/mk_output/infer/no_output/shm_ipc/shm_register/shm_bind…）。
  - 日志：analyzer.triton“run in_shape…”/SHM 注册失败日志节流（默认 1000ms），支持 `VA_LOG_THROTTLE_MS/VA_LOG_THROTTLED_LEVEL`。

## 构建/部署
- 修复 grpc 与 OpenSSL 链接：避免静态 libgrpc*.a，优先 `libgrpcclient.so`；增加 ldd 检查。
- `docker/va/Dockerfile.ort` 重写为单一多阶段，ORT 1.23.2 + CUDA 13，必要时启用 TRT EP；导出 `/opt/onnxruntime`（含 `.build.tag`）。

## 运行配置
- app.yaml 常用项：
  - `triton_url`, `triton_model(_version)`, `triton_input`, `triton_outputs`；
  - `triton_no_batch`(默认 false，对应 assume_no_batch)；
  - `triton_shm_cuda`(启用 SHM)，`triton_cuda_shm_bytes`(默认 8MB)，`triton_shm_server_device_id`；
  - `force_provider/providers` 节点级覆盖。
- 健康检查：`curl http://triton:8000/v2/health/ready`（容器内）或 `host.docker.internal:8000`（宿主）。

## 问题复盘
- 构建：`cudaIpcMemHandle_t` 重复定义 → 先包含 `cuda_runtime.h`；静态 GRPC 触发 OpenSSL DSO → 改为共享库并补 `libssl/libcrypto` 链接。
- 运行：
  1) 早期 VA 未命中 Triton；
  2) `batch-size must be <= 1` → 批次维自适配后恢复；
  3) `RegisterCudaSharedMemory invalid args` → 增加 Unregister-then-Register、唯一 SHM 名、server device id、输入/输出分侧禁用；
  4) 输出仍为 (cpu) → 因输入侧禁用被联动；现已解耦，输出可独立启用。

## 待办（下一阶段）
1) 深化自适配：解析 ModelConfig，严格校验 dtype/shape/max_batch_size；更精准批次维处理。
2) 输出 SHM 绑定按需字节数（必要时 offset 复用）。
3) 性能验证：Host vs SHM P50/P95 对比脚本与文档；确认 NMS GPU 路径直连 device Tensor。
4) 文档完善：Triton 部署、模型准备、常见错误与排查流程、示例与基线指标。
