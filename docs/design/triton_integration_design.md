# VA × Triton 整合设计（M0–M2）

本文在现有 VA/CP/VSM 架构上给出最小侵入、可演进的 Triton Inference Server 集成方案，遵循现有抽象（IModelSession/ModelSessionFactory/NodeModel）与零拷贝链路设计，并与现有回退链、日志与指标体系对齐。

## 1. 目标与范围

- 目标：
  - 在 VA 内以“会话实现”的方式接入 Triton（首期 gRPC 客户端），对接现有多阶段图“模型节点”。
  - 保持多阶段图与上下游节点不变；仅新增 IModelSession 实现与工厂映射。
  - 第一阶段优先功能正确与可观测；第二阶段引入 CUDA Shared Memory 以降低拷贝；第三阶段可选迁移到 Triton Ensemble。
- 不在本次范围：
  - 一次性替换现有预处理/NMS/Overlay；大规模接口调整；破坏回退链。

## 2. 接入点与抽象对齐

- 现有关键抽象：
  - `IModelSession`：统一 `loadModel/run/getRuntimeInfo/outputNames`；
  - `ModelSessionFactory`：依据 `EngineDescriptor` 决策 provider；
  - `NodeModel`：图中“模型节点”，内部仅调用 `IModelSession`；
  - `TensorView/ModelOutput`：基础张量与结果类型。
- 新增实现：
  - `TritonGrpcModelSession`（IModelSession 实现）
    - 使用 Triton C++ gRPC Client（`grpc_client.h`）。
    - 首期以 Host 内存（系统内存）对接；功能稳定后引入 CUDA Shared Memory 实现低拷贝。
  - `ModelSessionFactory` 新增 provider 映射：`triton|triton-grpc` → `TritonGrpcModelSession`。
- 回退链（建议）：
  - `tensorrt-native → triton → tensorrt(ORT-TRT) → cuda(ORT)`；Triton 不可用时自动降级本地会话，保障可用性。

## 3. API 与配置

- provider 选择：
  - `engine.provider: triton`（或 `triton-grpc`）
- 运行选项（`engine.options`）：
  - `triton_url: triton:8001`             # gRPC 端点
  - `triton_model: yolov12x`              # 模型名
  - `triton_model_version: ""`           # 空=latest
  - `triton_input: images`                # 输入名称
  - `triton_outputs: dets,proto`          # 输出名称（逗号分隔）
  - `triton_timeout_ms: 2000`             # RPC 超时
  - `triton_no_batch: false`              # 默认保留 batch 维（与 max_batch_size 对齐）
  - `triton_shm_cuda: false`              # T1 开启 CUDA Shared Memory（降低拷贝）
  - `triton_cuda_shm_bytes: 0`            # 预留容量（0=按首次输入推断）
  - `triton_cuda_shm_bytes: 0`            # 0=按首次输入推断
  - `device: 0`                           # 与 VA 设备一致
- NodeModel YAML 无需调整；仍通过 `model` 节点承载，路径字段在 Triton 模式下可忽略（由 Engine.options 指定模型信息）。

## 4. 目录与代码骨架

- 新增文件：
  - `video-analyzer/src/analyzer/triton_session.hpp`
  - `video-analyzer/src/analyzer/triton_session.cpp`
- 关键方法：
  - `loadModel(...)`：
    - 连接 Triton（gRPC）；拉取 Model Metadata/Config，缓存输入/输出名与 dtype/shape。
    - 若启用 CUDA SHM：注册输入/输出共享内存区（按容量或首次推断）。
  - `run(...)`：
    - Host 方案：将 `TensorView` 写入 `InferInput`，提交请求，取回 `InferRequestedOutput`，映射为 `TensorView`（host）。
    - CUDA SHM 方案：将设备缓冲注册为 SHM 或拷入已注册 SHM（避免重复注册/释放），请求完成后直接生成设备侧 `TensorView`。
  - `getRuntimeInfo()`：`provider=triton-grpc`，`gpu_active=true|false`（取决于 CUDA SHM 与落地策略），`device_binding`/`io_binding=false`。

## 5. 指标与日志

- 指标（Prom）：
  - `va_triton_rpc_seconds`（直方图：请求耗时；可加标签 model/op）
  - `va_triton_rpc_failed_total`（失败计数，标签：reason=create/invalid_input/mk_input/mk_output/infer/no_output/timeout/unavailable/other）
- 日志：
  - `[triton] call model=<name> bytes_in=<n> bytes_out=<m> ms=<x>`（节流，Warn 打印失败 fingerprints）

## 6. Compose 与部署

- 新增 `triton` 服务（同网段，GPU 注入）：

```yaml
services:
  triton:
    image: nvcr.io/nvidia/tritonserver:24.08-py3
    gpus: all
    command: ["tritonserver", "--model-repository=/models", "--grpc-port=8001", "--http-port=8000"]
    volumes:
      - ../../models:/models:ro
    ports: ["8001:8001", "8000:8000"]
```

- VA 设置 `engine.provider=triton` 与 `engine.options.triton_*` 指定 URL/模型与 IO 名称。

## 7. 推进阶段（M0→M2）

- M0（2–3 天）功能通：
  - gRPC + Host 内存路径；可观测（直方图/失败计数）；回退链可用。
- M1（2–4 天）性能化：
  - CUDA SHM 输入/输出；固定输入尺寸（1×3×640×640）下验证零/低拷贝；流同步与内存复用稳定。
- M2（3–5 天）深化：
  - 动态形状与批量；可选 Ensemble（将 NMS/Overlay 迁至 Triton）；熔断与健康探测；基准报告固化。

## 8. 风险与缓解

- 依赖打包：Triton C++ Client 无通用包；使用 third_party 或预构建镜像工具链；首期先 Host 内存路径降低依赖敏感性。
- CUDA SHM 生命周期：按容量复用/扩容；严格注册/注销顺序，避免泄漏；动态 shape 触发重注册与回退。
- 时序：提交前确保预处理 CUDA 流同步；必要时事件栅栏。
- dtype/布局：对齐 FP16/FP32 映射；输出名与顺序与模型配置保持一致（从 metadata 解析）。

## 9. 基准与验收

- 指标：`FPS`、`va_frame_latency_ms` P50/P95、`va_triton_rpc_seconds`；
- 验收：boxes>0，无 NVENC/NVDEC 报错；回退链在 Triton 不可用时自动生效；冷启加载时长纳入 `va_model_session_load_seconds`。

---

附：未来可选将 `provider: triton-inproc` 对接 Triton C API（进程内），但优先级低于 gRPC 方案。
