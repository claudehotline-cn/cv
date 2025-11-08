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

