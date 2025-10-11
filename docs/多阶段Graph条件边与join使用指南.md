# 多阶段 Graph：条件边与 node_join 使用指南

本文说明多阶段 Analyzer 图中的条件边语法，以及多输入拼接节点 `join` 的用法与注意事项。

## 条件边（when/when_not）

- 语法（YAML）：
  edges:
    - [src, dst]                                # 普通边
    - [src, dst2, { when: "attr:flag" }]       # 当包内 attrs["flag"] 为真时触发
    - [src, dst3, { when_not: "attr:skip" }]   # 当包内 attrs["skip"] 不为真时触发

- 取值规则：
  - `attr:<key>` 从 Packet.attrs 读取布尔值（字符串支持 "1/true/yes/on" 为真；"0/false/no/off" 为假；数值非零为真）。
  - 节点在执行时，如果存在任意条件边，至少需满足一条条件边才会运行（无条件边则按普通拓扑执行）。

- 校验与日志：
  - 同一条边同时出现 `when` 与 `when_not`，会记录 Warn，并优先使用 `when`。
  - Graph.finalize() 会做 I/O 校验，提示未被消费的输出、重复输出键等问题。

## 多输入拼接节点：join

- 类型：`type: join`
- 作用：将多个形状兼容的张量在指定 `axis` 维度上拼接（concatenate）。

- 参数：
  - `ins`: 输入键列表（字符串或列表）。示例：`ins: ["tensor:feat_a", "tensor:feat_b"]`
  - `out`: 输出键名。示例：`out: tensor:feat_joined`
  - `axis`: 拼接维度（默认 1；可为负数，表示从尾部数）。
  - `prefer_gpu`: 优先走 GPU 拼接，需所有输入都在 GPU 且上下文提供 `gpu_pool`（默认 1）。

- 兼容性约束：
  - 所有输入张量 rank 必须一致；除 `axis` 外的各维度必须相同。
  - 数据类型当前默认 `float32`，与 pipeline 约定保持一致。

- 性能注意：
  - GPU 路径在设备侧完成内存拼接，并复用 `GpuBufferPool` 分配。
  - 提供 `cudaStream_t`（经 `NodeContext.stream`）时使用 `cudaMemcpyAsync`；否则回落同步拷贝。

## 与 NodeModel 输出名的配合

- `node_model` 在未配置 `outs` 或 `outs` 数量不足时，会自动读取 ONNX Runtime 的真实输出名，并生成键：`tensor:<输出名>`；无法获取时回退为 `tensor:out{i}`。
- 为兼容单阶段旧图，首个输出仍提供别名：`tensor:det_raw`。

## 示例

```yaml
analyzer:
  multistage:
    nodes:
      - { name: pre,  type: preproc.letterbox, params: { out: tensor:img } }
      - { name: det,  type: model.ort,        params: { in: tensor:img, model_path: models/yolov8.onnx } }
      - { name: nms,  type: post.yolo.nms,    params: { in: tensor:det_raw, out: det.boxes } }
      - { name: join, type: join,             params: { ins: [tensor:feat_a, tensor:feat_b], out: tensor:feat, axis: -1 } }
      - { name: ovl,  type: overlay.cuda,     params: { in: det.boxes } }
    edges:
      - [pre, det]
      - [det, nms]
      - [nms, ovl, { when_not: "attr:skip_overlay" }]
```

## 故障排查

- 没有触发下游节点：检查条件边 `when/when_not` 的属性键是否正确写入 `Packet.attrs`。
- `join` 报 shape/rank 错：确认各输入张量除 `axis` 外维度完全一致；检查 `axis` 是否落在合法范围。
- GPU 拼接未生效：确认所有输入 `on_gpu=true` 且已配置设备侧池（EngineManager → NodeContext）。

## 相关日志与节流

- 可通过引擎选项或环境变量配置多阶段节点日志级别/节流，详见 `docs/日志与节流配置.md`。

