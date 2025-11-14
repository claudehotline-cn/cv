# Video Analyzer Metrics Guide

本指南概述后端暴露的 Prometheus 指标、标签约定、配置开关与常用 PromQL。

## 配置开关（observability）

在 `app.yaml` 中：

- `observability.pipeline_metrics_enabled`：是否启用内部周期性管线统计（与 /api/system/stats 相关）。
- `observability.pipeline_metrics_interval_ms`：统计周期（毫秒）。
- `observability.metrics.registry_enabled`（默认 `true`）：启用统一的 /metrics 导出路径（轻量文本构建器）。
  - 关闭时回退为旧版导出逻辑，指标名保持一致。
- `observability.metrics.extended_labels`（默认 `false`）：是否输出扩展标签（`decoder`/`encoder`/`preproc`）。
  - 默认关闭以避免标签基数增加；开启后可更细粒度过滤。

参考片段见 `docs/app_observability_snippet.yaml`。

## 标签约定

- 基本标签（默认始终输出）
  - `source_id`：源路标识（订阅时的 stream_id）。
  - `path`：处理路径形态（取值：`d2d` | `gpu` | `cpu`），判定规则详见 `docs/metrics_path_labels.md`。
- 扩展标签（`extended_labels=true` 时输出）
  - `decoder`：`nvdec` / `ffmpeg` / `other`
  - `encoder`：编码器名/族（如 `h264_nvenc` / `libx264` 等）
  - `preproc`：`cuda` / `cpu`（基于引擎选项 `use_cuda_preproc` 推断）

## 指标清单

- 系统级
  - `va_pipelines_total`（gauge）：总管道数
  - `va_pipelines_running`（gauge）：运行中管道数
  - `va_pipeline_aggregate_fps`（gauge）：汇总 FPS
  - `va_transport_packets_total` / `va_transport_bytes_total`（counter）：聚合传输包/字节数
  - `va_d2d_nv12_frames_total` / `va_cpu_fallback_skips_total`（counter）：全局零拷贝/CPU 回退相关
  - `va_encoder_eagain_retry_total`（counter）：全局 EAGAIN drain+retry 次数
  - `va_overlay_nv12_kernel_hits_total` / `va_overlay_nv12_passthrough_total`（counter）：叠加核统计

- 每源/每管道（带 `source_id`,`path` 标签；在扩展标签开启时还包含 `decoder`/`encoder`/`preproc`）
  - `va_pipeline_fps`（gauge）：管道 FPS
  - `va_frames_processed_total` / `va_frames_dropped_total`（counter）：处理/掉帧计数（总量）
  - `va_frame_latency_ms_*`（histogram）：分阶段时延直方图（`stage=preproc|infer|postproc|encode`）
    - 桶（毫秒）：1,2,5,10,20,50,100,200,500,1000；包含 `_bucket`、`_sum`（ms）、`_count`

- 编码器（每源）
  - `va_encoder_packets_total{source_id, path, [encoder,decoder,preproc]}`（counter）：已编码包数（以传输层计）
  - `va_encoder_bytes_total{...}`（counter）：已编码字节数
  - `va_encoder_eagain_total{...}`（counter）：编码 EAGAIN 次数（当前来源于零拷贝指标计数）

- 掉帧原因（每源）
  - `va_frames_dropped_total{source_id, reason}`（counter）：`reason=queue_overflow|decode_error|encode_eagain|backpressure`

- 源事件（每源）
  - `va_rtsp_source_reconnects_total{source_id}`（counter）：RTSP 源调度重连成功次数
  - `va_nvdec_device_recover_total{source_id}`（counter）：NVDEC 从 CPU fallback 恢复到设备路径次数
  - `va_nvdec_await_idr_total{source_id}`（counter）：NVDEC 等待 IDR 事件（启动/重连时）

## 常用 PromQL 示例

- 源路 FPS：`sum by (source_id, path) (rate(va_frames_processed_total[1m]))`
- 掉帧比例：`sum by (source_id,path)(rate(va_frames_dropped_total[5m])) / sum by (source_id,path)(rate(va_frames_processed_total[5m]))`
- P95 延时：`histogram_quantile(0.95, sum by (le,stage,source_id,path) (rate(va_frame_latency_ms_bucket[5m])))`
- 回压与溢出：
  - `sum(rate(va_frames_dropped_total{reason="backpressure"}[5m]))`
  - `sum(rate(va_frames_dropped_total{reason="queue_overflow"}[5m]))`
- 编码码率（bps）：`8 * sum by (source_id, path) (rate(va_encoder_bytes_total[1m]))`
- RTSP 与 NVDEC 事件：
  - `rate(va_rtsp_source_reconnects_total[10m])`
  - `rate(va_nvdec_device_recover_total[10m])`
  - `rate(va_nvdec_await_idr_total[10m])`

更多示例见 `docs/promql_examples.md`。

## 性能与基数控制

- 统一导出路径（默认开启）：`metrics_registry_enabled=true` 使用轻量文本构建器输出指标，避免手写拼接与重复开销。
- 分片存储（低锁争用）：
  - DropMetrics / SourceReconnects / NvdecEvents 采用 16 分片，增量操作仅持分片锁，快照逐片加锁汇总。
- 标签基数：
  - 默认仅输出基础标签 `source_id`、`path`；`extended_labels=false` 时与历史看板/告警完全兼容。
  - 如需诊断，开启 `extended_labels=true` 可附加 `decoder/encoder/preproc` 标签；建议仅在必要时启用。

## Path 判定说明

详见 `docs/metrics_path_labels.md`：`d2d` > `gpu(nvenc)` > `cpu` 的优先级，及语义说明。

---

如需新增指标，建议：
- 计数类：按 source 分片存储，增量使用原子或分片锁累加；
- 直方图：在运行热路径内部维护（如 Pipeline），导出阶段统一序列化；
- 标签：仅在必要时扩展，并通过开关控制，避免 TSDB 基数膨胀。
