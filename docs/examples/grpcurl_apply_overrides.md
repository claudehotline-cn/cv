# AnalyzerControl ApplyPipeline / ApplyPipelines 示例（grpcurl）

前置：控制面已内置并开启，默认监听 `0.0.0.0:50051`（无须传入 USE_GRPC/VA_ENABLE_GRPC_SERVER 开关）。

## 单条调用 ApplyPipeline

准备 JSON，保存为 `grpc_apply_pipeline.json`：

```
{
  "pipeline_name": "p1",
  "revision": "r001",
  "spec": {
    "graph_id": "analyzer_multistage_example",
    "overrides": {
      "node.nms.conf": "0.50",
      "node.nms.iou": "0.50",
      "type:overlay.cuda.thickness": "3",
      "engine.provider": "cuda",
      "engine.device": "0",
      "engine.options.use_cuda_nms": "true",
      "engine.options.use_nvdec": "true",
      "engine.options.use_nvenc": "true"
    }
  },
  "project": "projA",
  "tags": ["prod", "yolo"]
}
```

调用：

```
grpcurl -plaintext -d @ 127.0.0.1:50051 va.v1.AnalyzerControl/ApplyPipeline < grpc_apply_pipeline.json
```

## 批量调用 ApplyPipelines

准备 JSON，保存为 `grpc_apply_pipelines.json`：

```
{
  "items": [
    {
      "pipeline_name": "p1",
      "revision": "r001",
      "spec": {
        "graph_id": "analyzer_multistage_example",
        "overrides": {
          "node.nms.conf": "0.55",
          "engine.options.use_cuda_nms": "true"
        }
      },
      "project": "projA",
      "tags": ["prod"]
    },
    {
      "pipeline_name": "p2",
      "revision": "r002",
      "spec": {
        "template_id": "analyzer_multistage_example",
        "overrides": {
          "type:overlay.cuda.thickness": "4",
          "engine.provider": "cuda",
          "engine.device_index": "0",
          "engine.options.render_cuda": "true"
        }
      },
      "project": "projB",
      "tags": ["staging"]
    }
  ]
}
```

调用：

```
grpcurl -plaintext -d @ 127.0.0.1:50051 va.v1.AnalyzerControl/ApplyPipelines < grpc_apply_pipelines.json
```

## 参数约定与回滚

- 节点覆盖写法
  - `node.<节点名>.<参数>=值`
  - `type:<节点类型>.<参数>=值`，同类型节点批量生效。
- 引擎覆盖写法（EngineDescriptor 全量）
  - `engine.provider` / `engine.name` / `engine.device|engine.device_index`
  - `engine.options.<k>=<v>` 对应 `app.yaml/engine.options`

