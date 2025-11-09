## Triton 后端参数字典与映射（P2）

仅针对 In‑Process Triton 路线，推荐通过 VA 的 `engine.options.triton_backend_configs` 注入后端参数（等价 `--backend-config`）。多项以分号 `;` 分隔，每项形如 `backend:key=value`。

- 常用后端：
  - TensorRT：`tensorrt:...`
  - ONNX Runtime：`onnxruntime:...`

示例（写入 `app.yaml -> engine.options.triton_backend_configs`）：
- `tensorrt:coalesce_request_input=1;tensorrt:engine_cache_enable=true`
- `onnxruntime:session_thread_pool_size=4;onnxruntime:gpu_mem_limit_mb=4096`

约定映射
- VA 配置 → Triton ServerOptions
  - `triton_backend_dir` → `SetBackendDirectory`
  - `triton_pinned_mem_mb` → `SetPinnedMemoryPoolByteSize`
  - `triton_cuda_pool_device_id` + `triton_cuda_pool_bytes` → `SetCudaMemoryPoolByteSize`
  - `triton_backend_configs` → `SetBackendConfig(backend,key,value)`（多项）
- VA 配置 → 模型级 config.pbtxt（需按模型仓库维护）
  - 动态批：`dynamic_batching.preferred_batch_size`, `max_queue_delay_microseconds`
  - 实例并发：`instance_group.kind/count/gpus`
  - ORT TensorRT EP：`optimization.execution_accelerators.gpu_execution_accelerator{name:"tensorrt" parameters{ key:"precision_mode" value:"FP16" }}`

建议组合
- 动态批 + 并发：
  - config.pbtxt：`preferred_batch_size: [1,4,8]`、`max_queue_delay_microseconds: 2000`、`instance_group { kind: KIND_GPU count: 1 gpus: [0] }`
  - 后端（可选）：`tensorrt:coalesce_request_input=1`
- TensorRT 性能/稳定：
  - `tensorrt:engine_cache_enable=true`（启用引擎缓存）
  - 版本兼容：`tensorrt:version_compatible=true`（仅在引擎构建与运行时版本差异较小时使用）
- ORT TensorRT EP：
  - 在模型 `config.pbtxt` 配置 execution_accelerators；
  - 或通过 `onnxruntime:*` 后端参数（例如 `onnxruntime:session_thread_pool_size`）。

注意
- 后端参数键取决于 Triton 版本与后端 README；生产前应以实际发行版核验。
- config.pbtxt 输入/输出维度需与模型一致；示例仅示意。

