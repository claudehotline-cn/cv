# Triton 集成快速上手（T0：gRPC + Host 内存）

## 1) 准备模型仓库

Triton 需要如下目录结构（compose 已将 `docker/model` 映射为容器 `/models`）：

```
/docker/model
  └─ yolov12x
      ├─ config.pbtxt
      └─ 1/
         └─ model.onnx
```

- 将现有 ONNX 复制到版本目录：
  - `mkdir -p docker/model/yolov12x/1`
  - `cp docker/model/yolov12x.onnx docker/model/yolov12x/1/model.onnx`
- 编写最小 `config.pbtxt`（示例，按你的模型调整 IO 名称/维度）：

```
name: "yolov12x"
backend: "onnxruntime"
max_batch_size: 0
input [
  { name: "images", data_type: TYPE_FP32, dims: [1,3,640,640] }
]
output [
  { name: "dets", data_type: TYPE_FP32, dims: [-1] }
]
instance_group [ { kind: KIND_GPU, count: 1 } ]
```

> 注：维度与名称需与实际 ONNX 一致；不一致会导致推理失败或输出为空。

## 2) 启动 Triton 与 VA

- 启动 Triton：
  - `docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml up -d triton`
- 使用示例 VA 配置：`docker/config/va/app.triton.yaml`
  - 保持 `engine.provider: triton`
  - `triton_url: triton:8001`，`triton_model: yolov12x`，`triton_input: images`，`triton_outputs: dets`
- 启动 VA 与 CP：
  - `docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml up -d va cp`

## 3) 触发订阅与校验

- 创建订阅：

```
curl -sS -X POST http://127.0.0.1:18080/api/subscriptions \
 -H 'Content-Type: application/json' \
 -d '{"stream_id":"cam1","profile":"det_720p","source_uri":"rtsp://192.168.50.78:8554/camera_01"}'
```

- 查看指标：
  - `curl -s http://127.0.0.1:9090/metrics | rg 'va_triton_rpc_seconds|va_pipeline_fps'`
- 查看日志：
  - `docker logs -f va | rg 'analyzer.triton|ms.node_model|ms.nms'`

## 4) 回退链测试

- 停 Triton：`docker stop triton` → 观察 VA 自动降级至 tensorrt/cuda，指标 `va_triton_rpc_failed_total` 增加
- 启 Triton：`docker start triton` → `va_triton_rpc_seconds_count` 再次递增

## 5) 常见问题

- `va_triton_rpc_seconds_count=0`：
  - 确认 VA 二进制编译时启用 `-DUSE_TRITON_CLIENT=ON` 且 `TRITON_CLIENT_ROOT` 有效；
  - 检查 `triton_url` 是否可达；`tritonserver` 日志是否加载了模型。
- `boxes=0`：
  - 降低 NMS `conf`，对齐输出布局与后处理；优先验证 ONNX 输出在 Triton 中是否符合预期。
# Triton 集成快速上手（T0：gRPC + Host 内存）

本指南帮助你在当前 Compose 环境下，快速验证 VA→Triton 的 gRPC 推理路径。

## 1. 准备模型仓库

目录结构（Compose 已将 `docker/model` 挂载到 Triton `/models`）:

```
docker/model/
  └─ yolov12x/
      ├─ config.pbtxt
      └─ 1/
         └─ model.onnx
```

`config.pbtxt` 示例（按实际 ONNX 调整 IO 名称/维度）：

```
name: "yolov12x"
backend: "onnxruntime"
max_batch_size: 1
input [{ name: "images", data_type: TYPE_FP32, dims: [3,640,640] }]
output [{ name: "output0", data_type: TYPE_FP32, dims: [84,8400] }]
instance_group [{ kind: KIND_GPU, count: 1 }]
```

> 若 `max_batch_size: 0`（非批处理），建议在 VA 的 `app.yaml` 中设置 `engine.options.triton_no_batch: true`。

## 2. 启动服务

```
docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml up -d triton va
```

## 3. VA 配置关键项（`docker/config/va/app.yaml`）

```
engine:
  provider: triton
  device: 0
  options:
    use_multistage: true
    graph_id: analyzer_multistage_example
    force_provider: triton
    triton_url: triton:8001
    triton_model: yolov12x
    triton_input: images
    triton_outputs: output0
    triton_timeout_ms: 5000
    # 非批处理模型可开启：
    # triton_no_batch: true
    # 可选：启用 In‑Process Triton（不改 provider，减少 gRPC/IPC 开销）
    # triton_inproc: true
    # triton_repo: /models
    # triton_enable_http: false
    # triton_enable_grpc: false

### 3.1 预构建 ORT 基镜像（推荐）

为了避免每次构建都重新编译 ONNX Runtime，可先构建一个仅包含 `/opt/onnxruntime` 的基础镜像，然后 VA 镜像直接复用：

1) 构建 ORT 基镜像（CUDA13 + cuDNN + devel 基镜像）：

```
docker build -f docker/va/Dockerfile.ort \
  --build-arg ORT_VERSION=1.23.2 \
  --build-arg CUDA_DEVEL_TAG=13.0.0-cudnn9-devel-ubuntu22.04 \
  --build-arg CUDARCHS=120 \
  -t cv/va-ort:1.23.2-cuda13 .
```

2) 构建 VA 时复用预构建 ORT：

```
docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml \
  build va --build-arg ORT_PREBUILT_IMAGE=cv/va-ort:1.23.2-cuda13
```

Dockerfile 会优先从 `ORT_PREBUILT_IMAGE` 拷贝 `/opt/onnxruntime`；若不存在则回退为源码构建（仅首次耗时）。
```

## 4. 触发订阅与观测

创建订阅（通过 CP）：

```
curl -sS -X POST http://127.0.0.1:18080/api/subscriptions \
 -H 'Content-Type: application/json' \
 -d '{"stream_id":"camera_01","profile":"det_720p","source_uri":"rtsp://192.168.50.78:8554/camera_01"}'
```

观测指标与日志：

```
curl -s http://127.0.0.1:9090/metrics | rg 'va_triton_rpc_seconds|va_triton_rpc_failed_total'
docker logs va | rg 'analyzer.triton|ms.node_model'
```

## 5. 常见问题

- `inference request batch-size must be <= 1`：
  - 你的模型 `max_batch_size` 为 1，需保留 batch 维（`1x3x640x640`），不要设置 `triton_no_batch:true`。
- `va_triton_rpc_seconds_count=0`：
  - 检查二进制是否链接 `libgrpcclient.so`；`ldd /app/bin/VideoAnalyzer | rg grpcclient`。
  - 检查 `triton_url` 可达；`curl -s http://triton:8000/v2/health/ready` 应返回 200。
- `failed to open CUDA IPC handle: invalid resource handle` / `RegisterCudaSharedMemory failed: invalid args`：
  - 多见于 VA 与 Triton 进程使用了不同的 `CUDA_VISIBLE_DEVICES` 映射，导致传给服务端的 device_id 与服务器侧序号不一致；
  - 解决：确保两进程的 GPU 映射一致，或在 `engine.options` 设置 `triton_shm_server_device_id` 为服务端看到的设备序号（通常是 `0`）；
  - 已加入保护：连续失败（默认≥3）后将自动禁用 CUDA SHM 并回退至 Host 路径，避免日志刷屏；阈值可用 `triton_shm_fail_threshold` 调整。
  - 若仍失败，请检查容器内 CUDA 主版本是否一致（VA vs Triton）。不同 CUDA 主版本（例如 VA 使用 13.x 而 Triton 基于 12.x）会导致 IPC 句柄无法在服务端打开。若你需要保持 VA=CUDA 13.0，请将 Triton 也切到 CUDA 13：
    - 在 `docker/compose/docker-compose.gpu.override.yml` 里设置：
      - `EXPECTED_CUDA_MAJOR: "13"`, `EXPECTED_CUDA_MINOR: "0"`
      - `TRITON_TAG: "25.10-py3"`（示例；若拉取失败，可尝试 `25.09-py3` 或与你私库可用的 CUDA13 版本）
      - `NGC_TRT_TAG: "25.10-py3"` 以对齐 TensorRT 基础镜像（同样可尝试 25.09）
    - 之后 `docker compose -f docker/compose/docker-compose.yml -f docker/compose/docker-compose.gpu.override.yml build va && docker compose -f ... up -d --force-recreate va`

### 用 Docker 快速对齐 GPU 序号

当 Triton 与 VA 在同一个容器（本项目 GPU 方案默认）时（In‑Process 推荐开启）：

```
docker exec -it va bash -lc 'echo CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES; env | rg NVIDIA_VISIBLE_DEVICES || true; nvidia-smi -L'
```

若 Triton 为独立容器（你自定义部署）：

```
docker exec -it triton bash -lc 'echo CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES; env | rg NVIDIA_VISIBLE_DEVICES || true; nvidia-smi -L'
docker exec -it va     bash -lc 'echo CUDA_VISIBLE_DEVICES=$CUDA_VISIBLE_DEVICES; env | rg NVIDIA_VISIBLE_DEVICES || true; nvidia-smi -L'
```

将 Triton 容器内看到的 GPU 序号（通常为 0）填入 `engine.options.triton_shm_server_device_id`，重启 VA。若使用 In‑Process（推荐），也可以设置 `VA_TRITON_EXTERNAL=0` 并在构建时开启 `VA_USE_TRT_INPROC=ON`，此时无需 CUDA IPC。
