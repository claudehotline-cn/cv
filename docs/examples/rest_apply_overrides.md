# REST 映射：ApplyPipeline / ApplyPipelines 示例

服务启动：`VideoAnalyzer.exe .\config\`（需开启内嵌控制面 USE_GRPC=ON, VA_ENABLE_GRPC_SERVER=ON）。

路由
- POST `/api/control/apply_pipeline`
- POST `/api/control/apply_pipelines`

公共字段说明
- `pipeline_name`：必填
- `graph_id | yaml_path | template_id`：三选一，至少提供一个
- `overrides`：节点/类型/引擎覆写（见键名约定）
- `project`/`tags[]`：可选元信息

键名约定
- 节点参数覆写：`node.<节点名>.<参数>=值`
- 类型批量覆写：`type:<节点类型>.<参数>=值`
- 引擎覆写（全局）：
  - `engine.provider` / `engine.name` / `engine.device|engine.device_index`
  - `engine.options.<k>=<v>`（对应 `app.yaml/engine.options`）

示例：单条下发
```
POST http://127.0.0.1:8082/api/control/apply_pipeline
Content-Type: application/json

{
  "pipeline_name": "p1",
  "revision": "r001",
  "graph_id": "analyzer_multistage_example",
  "project": "projA",
  "tags": ["prod", "yolo"],
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
}
```

示例：批量下发
```
POST http://127.0.0.1:8082/api/control/apply_pipelines
Content-Type: application/json

{
  "items": [
    {
      "pipeline_name": "p1",
      "revision": "r001",
      "graph_id": "analyzer_multistage_example",
      "project": "projA",
      "tags": ["prod"],
      "overrides": {
        "node.nms.conf": "0.55",
        "engine.options.use_cuda_nms": "true"
      }
    },
    {
      "pipeline_name": "p2",
      "revision": "r002",
      "template_id": "analyzer_multistage_example",
      "project": "projB",
      "tags": ["staging"],
      "overrides": {
        "type:overlay.cuda.thickness": "4",
        "engine.provider": "cuda",
        "engine.device_index": "0",
        "engine.options.render_cuda": "true"
      }
    }
  ]
}
```

curl 示例
```
curl -sS -X POST http://127.0.0.1:8082/api/control/apply_pipeline \
  -H "Content-Type: application/json" \
  -d @docs/examples/overrides_examples.json \
  | jq .

curl -sS -X POST http://127.0.0.1:8082/api/control/apply_pipelines \
  -H "Content-Type: application/json" \
  -d @docs/examples/overrides_examples.json \
  | jq .
```

