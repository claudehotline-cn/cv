# VA/CP/VSM 基准测试指南（M2）

本文给出在 GPU 环境下对三种推理路径进行端到端基准的最小流程与采样脚本，目标产出 FPS 与阶段延迟（P50/P95）。

## 一、对象与指标

- 对象：Video Analyzer（VA）端到端管线（RTSP → 预处理 → 推理 → 后处理 → 叠加 → 编码 → WHEP）。
- 路径：
  - ORT CUDA（`engine.provider=cuda`）
  - ORT TensorRT EP（`engine.provider=tensorrt`）
  - 原生 TensorRT（`engine.provider=tensorrt-native`，可选启用 `trt_serialize_on_build`）
- 指标：
  - FPS：`va_pipeline_fps`（Prom）
  - 阶段延迟：`va_frame_latency_ms`（按 `stage=preproc|infer|postproc|encode` 导出直方图；计算 P50/P95）
  - 加载/预热：`va_model_session_load_seconds` 与 `va_graph_open_duration_seconds`（冷启动感知）

## 二、准备

- 启动 Compose（GPU 注入）：
  - `docker/compose/docker-compose.yml` + `docker/compose/docker-compose.gpu.override.yml`
  - 确保 `gpus: all` 与 `/app/models` 映射；模型文件（ONNX/.engine）置于相对路径 `models/…`
- VA 配置：在 `video-analyzer/config/app.yaml` 或环境变量中设置：
  - `engine.provider: cuda|tensorrt|tensorrt-native`
  - 可选 `engine.options.trt_serialize_on_build: true`、`engine.options.trt_engine_dir: /app/.trt_native_cache/engines`
- RTSP 源：可使用示例源或测试服务器（例如：`rtsp://192.168.50.78:8554/camera_01`）

## 三、采样脚本

仓库已提供 `video-analyzer/test/scripts/benchmark_metrics.py`：

- 仅依赖 `requests`；从 `VA /metrics` 读取 Prometheus 文本，计算：
  - 平均 FPS
  - 阶段延迟 P50/P95（按直方图近似）
- 用法：

```
python3 video-analyzer/test/scripts/benchmark_metrics.py \
  --metrics http://127.0.0.1:9090/metrics \
  --label tensorrt-native --duration 30
```

- 输出示例：

```
{
  "label": "tensorrt-native",
  "fps": 28.6,
  "latency_ms": {
    "preproc": {"p50": 3.2, "p95": 6.7},
    "infer":   {"p50": 12.4, "p95": 20.1},
    "postproc":{"p50": 1.1, "p95": 2.3},
    "encode":  {"p50": 4.5, "p95": 9.0}
  }
}
```

> 注：脚本默认为单路管线；多路场景下按 `source_id` 聚合平均值。

## 四、流程建议

1. 依次以三种 provider 启动 VA（或在不同容器实例中分别运行）。
2. 每种 provider 下运行脚本 30–60 秒，保存 JSON 输出至 `docs/examples/results/`。
3. 对比 FPS 与 `infer` 阶段 P95（吞吐与高分位拉长）。

## 五、报告模板

建议使用 `docs/plans/benchmark-report-template.md`，包含：环境（GPU/驱动/ORT/TRT 版本）、模型与输入分辨率、配置（预热/缓存）、结果表格（FPS/P50/P95）、结论与建议。

---

排错要点：若 `va_model_session_load_failed_total>0` 或 `boxes=0`，先降低 NMS 置信度（示例 YAML `conf: 0.25`）并检查模型导出（输出 tensor 是否存在）。

