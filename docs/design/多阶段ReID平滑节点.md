# 多阶段节点：reid.smooth（跨帧缓存平滑）

本节点用于对 ReID 特征向量进行跨帧平滑，降低抖动。节点内部维护按 `id_attr`（通常是跟踪 ID）划分的小缓存，不修改核心类型与上下文结构。

## 类型与参数

- 类型：`reid.smooth`
- 参数：
  - `in`: 输入张量键（F32，形状 `[D]` 或 `[1,D]`）。
  - `out`: 输出张量键（默认 `tensor:reid_smooth`）。
  - `id_attr`: 从 `Packet.attrs` 读取的 ID 键（默认 `track_id`）。支持 `int/float/double/string`，会转成字符串用作 Key。
  - `method`: 平滑方法，`ema`（默认）或 `mean`。
  - `window`: `mean` 方法使用的窗口大小（默认 10）。
  - `decay`: `ema` 衰减系数，表示历史权重（默认 0.9）。
  - `l2norm`: 输出是否做 L2 归一化（默认 1/true）。
  - `passthrough_if_missing`: 缺少 `id_attr` 时是否透传输入（默认 1/true）。

说明：当前实现仅支持 CPU 张量输入。如上游经 ORT IoBinding 在 GPU 输出，请在引擎选项开启 `stage_device_outputs=1` 以将输出暂存到主机内存，或在该节点之前添加一个将特征搬到 CPU 的节点（后续可扩展为 GPU kernel 版本）。

## 示例

```yaml
analyzer:
  multistage:
    nodes:
      - { name: model, type: model.ort, params: { in: tensor:img, model_path: models/reid.onnx, outs: [tensor:reid] } }
      - { name: smooth, type: reid.smooth, params: { in: tensor:reid, out: tensor:reid_smooth, id_attr: track_id, method: ema, decay: 0.9, l2norm: 1 } }
    edges:
      - [model, smooth]
```

## 运行时行为

- `ema`：`y_t = decay * y_{t-1} + (1 - decay) * x_t`，首次初始化为当前值。
- `mean`：维护长度不超过 `window` 的滑窗，输出为窗口内向量的均值；计算量与维度 D 线性相关。
- `l2norm`：对输出向量进行 L2 归一化，避免尺度漂移。

## 故障排查

- 日志包含 `ms.reid` 标签；若出现 `input on GPU` 警告，启用 `stage_device_outputs=1` 或改为让上游输出 CPU 张量。
- 如果 `missing id_attr`，请确保上游正确写入 `Packet.attrs[track_id]`。

