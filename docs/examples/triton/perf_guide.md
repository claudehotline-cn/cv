## Triton 动态批/实例并发调优指南（P4）

目标：用 perf_analyzer / model_analyzer 形成吞吐/延迟/显存基线，给出 `dynamic_batching.preferred_batch_size` 与 `instance_group.count` 的推荐值。

前置条件（In‑Process VA）
- 暂时开启 VA 的 Triton 端口（HTTP 或 gRPC 任一），供 perf_analyzer 访问：
  - `engine.options.triton_enable_grpc: true`（默认端口 8001）或 `triton_enable_http: true`（默认 8000）
- 令 `engine.options.triton_model` 指向目标模型（或 Ensemble）。

脚本与示例
- 运行 perf：
```
tools/triton/perf_analyze.sh -m ens_det_trt_full -u localhost:8001 -c 1,2,4,8 --protocol grpc --report det_perf.csv
```
- 生成推荐批次：
```
tools/triton/suggest_dynamic_batch.py --report det_perf.csv --latency-budget-ms 2.0
# 输出：{"preferred_batch_size": [1,2,4,8], ...}
```

落地到 config.pbtxt
- 在模型 `config.pbtxt` 更新：
```
dynamic_batching {
  preferred_batch_size: [1, 2, 4, 8]
  max_queue_delay_microseconds: 2000
}
instance_group [{ kind: KIND_GPU count: 1 gpus: [0] }]
```
- 如需并发实例：将 `instance_group.count` 提升为 2/3（受显存限制与隔离需求制约），再用 perf_analyzer 复测。

说明
- perf_analyzer 更适合固定模型测试；model_analyzer 可自动搜索 `preferred_batch_size × instance_group` 组合，输出更全面的建议，可按需补充使用。
- 时延预算建议：`P90 <= 2× baseline_p90` 作为粗略阈值；实际以业务 SLA 为准。
- 若使用 Ensemble，建议分别测试关键子模型与整体 Ensemble 以定位瓶颈。

