path 标签取值说明

概述
- 在 `/metrics` 暴露的 per-source 指标中，`path` 标签用于标识该源当前主要的数据处理路径形态，帮助在面板或告警中快速区分 CPU/GPU/D2D 的性能与稳定性差异。

取值范围与优先级
- 取值：`d2d` | `gpu` | `cpu`
- 优先级：`d2d` > `gpu` > `cpu`

判定规则（运行时启发式）
- `d2d`
  - 含义：NVDEC→NVENC 设备 NV12 零拷贝直通（device-to-device）。
  - 判定：当该源的 `zerocopy_metrics.d2d_nv12_frames > 0`。
- `gpu`
  - 含义：使用 NVENC 等 GPU 编码，但未达到 d2d（可能存在主机↔设备拷贝）。
  - 判定：编码器 `codec` 字符串包含 `nvenc`，且未命中 `d2d`。
- `cpu`
  - 含义：纯 CPU 路径（软件编码）或未检测到 GPU 参与。
  - 判定：不满足 `d2d`/`gpu` 条件时的默认值。

语义与使用建议
- 面板分组：在 Grafana 中按 `source_id`、`path` 分组更容易看出不同路径的性能差异。
- 指标覆盖：`path` 出现在以下 per-source 系列中：
  - `va_pipeline_fps{source_id,path}`
  - `va_frames_processed_total{source_id,path}`、`va_frames_dropped_total{source_id,path}`
  - 分阶段时延直方图：`va_frame_latency_ms_bucket{stage,source_id,path,le}`、`_sum{...}`、`_count{...}`
- 系统级合计：如 `va_pipeline_aggregate_fps`、`va_transport_bytes_total` 等系统合计指标不携带 `source_id/path` 标签。

示例
- `va_pipeline_fps{source_id="camera_01",path="d2d"} 29.7`
- `va_frame_latency_ms_bucket{stage="infer",source_id="camera_01",path="gpu",le="50"} 1234`

注意事项与后续扩展
- 启发式局限：当前版本仅依据零拷贝计数与编码器 `codec`（是否包含 `nvenc`）进行判定，可能无法覆盖所有硬件/驱动组合。
  - 辅助判断：可结合 `va_overlay_nv12_kernel_hits_total`、`va_cpu_fallback_skips_total` 等指标交叉验证路径特征。
- 可扩展标签：若需要更细粒度区分，建议后续增加：
  - `decoder`（如 `nvdec`/`ffmpeg`）、`encoder`（如 `nvenc`/`x264`/`qsv`/`amf`）
  - `preproc`（如 `cuda`/`cpu`）
  - 或汇总到 `path_detail`（例如 `nvdec+cuda+nvenc`）。

