## Triton Ensemble 示例（检测模型包裹）

本目录提供若干 Ensemble 配置，作为将检测模型“包裹”为 Ensemble 的起点：

- `ens_det_onnx/config.pbtxt`：单步封装子模型 `det_onnx_trt_ep`（参考 `docs/examples/triton/configs/onnx_det_trt_ep/config.pbtxt`）
- `ens_det_trt/config.pbtxt`：单步封装子模型 `det_trt_plan`（参考 `docs/examples/triton/configs/trt_det_sample/config.pbtxt`）
- `ens_det_onnx_full/config.pbtxt`：加入前处理(`preproc_letterbox`)与后处理(`yolo_nms`)的完整示例
- `ens_det_trt_full/config.pbtxt`：加入前处理与后处理的完整示例

说明：
- 这两个 Ensemble 目前只做“单步映射”（输入/输出转发至子模型），便于先打通 VA/MinIO/Triton 的 Ensemble 加载链路；后续可逐步加入额外步骤（例如后处理、ReID 等），或将多模型编排到 Ensemble 内。

目录结构（MinIO 模型仓库示例，含 Python 后端的前后处理）：

```
cv-models/
  models/
    det_trt_plan/
      1/
        model.plan
      config.pbtxt
    det_onnx_trt_ep/
      1/
        model.onnx
      config.pbtxt
    ens_det_trt/
      1/
        # 无文件；Ensemble 仅需要 config
      config.pbtxt
    ens_det_onnx/
      1/
      config.pbtxt
    ens_det_trt_full/
      1/
      config.pbtxt
    ens_det_onnx_full/
      1/
      config.pbtxt
    preproc_letterbox/
      1/
        model.py
      config.pbtxt
    yolo_nms/
      1/
        model.py
      config.pbtxt
```

上传与加载（以 MinIO 为例）：

1. 把子模型配置（`det_*`）和权重上传到 `cv-models/models/`；
2. 上传 Ensemble 目录与 `config.pbtxt`；
3. 在 VA 引擎中设置：

```
engine:
  options:
    provider: triton
    triton_inproc: true
    triton_repo: s3://http://minio:9000/cv-models/models
    triton_model: ens_det_trt    # 或 ens_det_onnx
    triton_model_version: ""     # 空=latest
```

4. 通过 CLI 验证：
   - 加载：`va_repo --va-addr 127.0.0.1:50051 load ens_det_trt`
   - 切换：`va_release --va-addr 127.0.0.1:50051 --pipeline det --node model --triton-model ens_det_trt`

后续扩展：
- 在 `ensemble_scheduling.step[]` 中继续追加步骤，并用 `input_map`/`output_map` 串联各子模型；
- 若需要在 Ensemble 内完成 NMS/格式转换，可使用对应后端（例如 Python/C++ 自定义后端或 TensorRT 插件模型）；
- 与项目现有多阶段（multistage）框架配合：多模型合并可放在 Ensemble，预处理/叠加仍可在进程内完成。
