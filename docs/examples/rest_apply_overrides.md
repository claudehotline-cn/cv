# REST：Apply Pipeline 与 Overrides 示例

## 单个 Apply（带占位替换与引擎覆盖）

- 目标：读取 YAML 并展开占位符 `${key}`。
- 取值顺序：`overrides.params.key` → `params.key` → `key`

示例（Windows PowerShell）：

```
$base = 'http://127.0.0.1:8082'
$yaml = 'D:/Projects/ai/cv/video-analyzer/build-ninja/bin/config/graphs/analyzer_multistage_example.yaml'
$body = @{
  pipeline_name = 'rest_demo_1'
  yaml_path = $yaml
  overrides = @{
    'params.w' = '800'
    'params.h' = '480'
    'engine.options.render_cuda' = 'false'
    'engine.options.use_io_binding' = '0'
  }
} | ConvertTo-Json -Depth 4

Invoke-WebRequest -UseBasicParsing -Method Post -ContentType 'application/json' -Body $body "$base/api/control/apply_pipeline"
```

返回：`{ code:"OK", success:true, accepted:true, warnings?:[] }`

## 批量 Apply

```
$base = 'http://127.0.0.1:8082'
$items = @{
  items = @(
    @{ pipeline_name='p1'; graph_id='analyzer_multistage_example' },
    @{ pipeline_name='p2'; yaml_path='D:/path/to/graph.yaml'; overrides=@{ 'params.w'='640'; 'params.h'='480' } }
  )
} | ConvertTo-Json -Depth 5
Invoke-WebRequest -UseBasicParsing -Method Post -ContentType 'application/json' -Body $items "$base/api/control/apply_pipelines"
```

## 未识别 overrides 提示

- 规则（静态检查，尽力而为）：
  - 已识别前缀：`engine.*`、`engine.options.*`、`params.*`、`overrides.params.*`、`node.*`、`type:*`
  - 其他键将出现在 `warnings` 数组中（不阻断 Apply）。

## 更多示例文件

- `docs/examples/overrides_examples.json`

