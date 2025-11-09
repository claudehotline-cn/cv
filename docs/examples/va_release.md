## VA 发布流程 CLI 使用说明（P1-T2）

该 CLI 仅作为最小可用工具，基于 VA 的 gRPC 接口实现“Load→Warmup→Alias(等价 HotSwap)”流程。

- 可执行文件：`controlplane/build/va_release`（随 controlplane 一起构建）
- 依赖：gRPC/Protobuf（controlplane 已配置生成与链接）

用法：

```
va_release --va-addr <host:port> --pipeline <name> --node <node> [--model-uri <path>] [--triton-model <name>] [--triton-version <ver>]
```

参数说明：
- `--va-addr`：VA gRPC 地址，如 `127.0.0.1:50051`
- `--pipeline`：目标管线名（与 ApplyPipeline 一致）
- `--node`：模型节点名（YAML 中的节点 ID）
- `--model-uri`：用于 ORT/TRT 本地/仓库模型路径；对 Triton 可省略
- `--triton-model`：Triton 模型名（覆盖 Engine 的 `triton_model`）
- `--triton-version`：Triton 模型版本（覆盖 Engine 的 `triton_model_version`）

流程语义：
- 若提供 `--triton-model`/`--triton-version`：先调用 `SetEngine(options)` 更新 VA 引擎选项；
- 随后调用 `HotSwapModel(pipeline,node,model_uri)` 触发节点重开会话：
  - ORT/TRT：使用 `model_uri` 加载；
  - Triton（含 In-Process）：`model_uri` 忽略，按引擎选项中的 `triton_model`/`triton_model_version` 加载；首次推理按 `warmup_runs` 预热。

注意：
- 别名切换（Alias）在 Triton 端对应“版本或目录别名”的治理；当前 CLI 将其等价为一次 `HotSwapModel`（逻辑别名→底层映射）以实现零中断上线。
- 需要显式仓库控制（`index/load/unload/poll`）时，可在 VA 内部调用 In‑Process C API（已封装至 Host），或在外部通过 S3/MinIO 完成模型目录操作后调用 `HotSwapModel`。

示例：
- 切换 Triton 模型到 `yolov12x@3`：
```
va_release --va-addr 127.0.0.1:50051 --pipeline det --node model --triton-model yolov12x --triton-version 3
```
- 切换 ORT 模型到本地文件：
```
va_release --va-addr 127.0.0.1:50051 --pipeline det --node model --model-uri /models/yolov8s.onnx
```

