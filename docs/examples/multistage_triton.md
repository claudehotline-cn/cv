## Multistage + Triton（In‑Process）示例（P3）

目标：基于多阶段图（预处理→模型→NMS→叠加），将模型阶段用 Triton（In‑Process 嵌入）执行。

示例图：`video-analyzer/config/graphs/analyzer_multistage_triton.yaml`

关键 Engine 配置（可在 `docker/config/va/app.yaml` 的 `engine.options` 中设置）：

```
use_multistage: true
graph_id: analyzer_multistage_triton
provider: triton
triton_inproc: true
triton_repo: s3://http://minio:9000/cv-models/models
triton_model: yolov12x
triton_model_version: ""   # 空=latest 或指定版本号
triton_gpu_input: true
triton_gpu_output: true
triton_timeout_ms: 2000
warmup_runs: auto
# 后端与池化（可选）
triton_backend_dir: /opt/tritonserver/backends
triton_pinned_mem_mb: 256
triton_cuda_pool_device_id: 0
triton_cuda_pool_bytes: 268435456   # 256MiB
triton_backend_configs: "tensorrt:coalesce_request_input=1;tensorrt:engine_cache_enable=true"
```

说明：
- YAML 中 `type: model` 使用当前 Engine 的 provider；当 provider=triton 时无需 `model_path`。
- 首帧将触发懒加载预热（`warmup_runs: auto` 时执行 1 次）。
- MinIO 仓库使用 `s3://http://minio:9000/...` 内嵌端点形式，以兼容 In‑Process 构建。

发布与切换：
- 可用 `va_repo` 进行仓库级操作：`load/unload/poll`；
- 用 `va_release` 覆盖 `triton_model(_version)` 后 `HotSwapModel`，实现零中断切换。

