# 日志与指标（Logging & Metrics）统一方案

## 目标与范围

- 统一后端日志规范（格式、前缀、级别、开关），减少刷屏。
- 建立可观测性指标（metrics）规范，便于 Prometheus 抓取与告警。
- 尽量最小侵入，渐进落地；Release 默认稳定（非 DEBUG 级刷屏）。

---

## 日志规范（后端）

### 级别与启用策略

- 级别：`TRACE < DEBUG < INFO < WARN < ERROR < FATAL`
- Release 默认：`INFO`；开发/排查可切至 `DEBUG/TRACE`
- 支持模块级覆盖：全局级别 + 模块级别（如 `transport.webrtc:debug,encoder.ffmpeg:info`）

### 模块命名（component）

- `core`、`source.ffmpeg`、`source.nvdec`、`analyzer`、`renderer.cpu`、`renderer.cuda`、
  `encoder.ffmpeg`、`encoder.nvenc`、`transport.webrtc`、`rest`、`pipeline`

### 统一前缀与结构化输出

- 文本（默认）：`[VA][{level}][{component}]{opt_ctx} msg`
  - `opt_ctx` 常见键：`src={source_id} cli={client_id} ssrc={ssrc} trk={track}`
- 结构化 JSON（可选）：
  {"ts":"...","level":"INFO","component":"transport.webrtc","msg":"...",
   "source_id":"...","client_id":"...","thread":"..."}
- 运行时选择输出模式：`VA_LOG_FORMAT=text|json`

### 限流与采样（防刷屏）

- 提供宏/工具：
  - `VA_LOG_EVERY_N(level, comp, N, "msg ...")`
  - `VA_LOG_THROTTLED(level, comp, period_ms, "msg ...")`
  - `VA_LOG_ONCE(comp, "msg ...")`
  - 聚合诊断：每 1s/5s 打印一次汇总（例如 WebRTC diag）
- 将高频逐帧日志降级为 `DEBUG` 并默认限流

### 上下文注入与关联

- 标准上下文键：`source_id`、`client_id`、`ssrc`、`track_id`、`codec`、
  `path=cpu|gpu|d2d|hw_xfer`、`width`、`height`
- 可选：`trace_id` / `span_id`

### 配置方式

- 环境变量：
  - `VA_LOG_LEVEL=info`
  - `VA_LOG_MODULE_LEVELS=transport.webrtc:debug,encoder.ffmpeg:info`
  - `VA_LOG_FORMAT=text|json`
  - `VA_LOG_FILE=logs/video-analyzer.log`
  - `VA_LOG_ROTATE_MB=50`，`VA_LOG_ROTATE_FILES=5`
- 运行时 REST：
  - `POST /api/logging/set`（全局级别、模块级别、格式切换、限流周期）
  - `GET /api/logging`（当前配置）

### 落地与轮转

- 文件输出：`logs/video-analyzer-{date}.log`，按大小/日期轮转（例如 50MB x 5）
- 控制台输出：开发可开，Release 默认仅文件
- 可选 JSON 行写独立文件 `*-json.log`

---

## 指标规范（Prometheus）

### 暴露方式

- 新增 `/metrics` 路由（Prometheus 文本格式）
- 采用轻量 Registry + 序列化，或接入 `prometheus-cpp`

### 指标与类型

- 帧处理与时延：
  - `va_frames_processed_total{source_id, path}` counter
  - `va_frames_dropped_total{source_id, reason}` counter（queue_overflow, decode_error, encode_eagain, backpressure…）
  - `va_frame_latency_ms_bucket{stage,source_id}` histogram（preproc/infer/postproc/encode 或总时延）
  - `va_pipeline_fps{source_id}` gauge
- 编码/传输：
  - `va_encoder_packets_total{codec, path}` / `va_encoder_bytes_total{codec, path}` counters
  - `va_encoder_eagain_total{codec}` counter
  - `va_webrtc_clients{state}` gauge（connected/completed/failed）
  - `va_webrtc_bytes_sent_total{source_id, client_id}` / `va_webrtc_frames_sent_total{...}` counters
- 解码/源：
  - `va_rtsp_source_reconnects_total{uri}` counter（注意高基数，必要时不打标签或做 hash）
  - `va_nvdec_await_idr_total{source_id}` counter
  - `va_source_fps{source_id}` gauge
- 资源与回退：
  - `va_gpu_mem_usage_bytes` gauge（可选）
  - `va_cpu_fallback_skips_total{path}` counter
  - `va_overlay_nv12_kernel_hits_total` / `va_overlay_nv12_passthrough_total` counters

### 标签规范（避免基数爆炸）

- `source_id` 控制在有限集合；`client_id` 可选（可通过聚合禁用）
- URI/文件名等高基数字段不要做 label，必要时 hash/分桶或仅记录在日志

### 采样与开关

- Histogram 桶建议（ms）：`[1,2,5,10,20,50,100,200,500,1000]`
- 开关：`VA_METRICS=on|off`，`VA_METRICS_VERBOSE=on|off`

### /metrics 字段示例

```
# HELP va_frames_processed_total Frames processed
# TYPE va_frames_processed_total counter
va_frames_processed_total{source_id="camera_01",path="gpu"} 12345

# HELP va_frame_latency_ms Frame processing latency
# TYPE va_frame_latency_ms histogram
va_frame_latency_ms_bucket{stage="infer",le="5"} 100
...
va_frame_latency_ms_sum{stage="infer"} 12345
va_frame_latency_ms_count{stage="infer"} 678
```

### 告警点（PromQL）

- FPS 低：`sum(rate(va_frames_processed_total{source_id="camera_01"}[1m])) < 10`
- 丢帧率：`sum(rate(va_frames_dropped_total[5m])) / sum(rate(va_frames_processed_total[5m])) > 0.1`
- 编码异常：`increase(va_encoder_eagain_total[5m]) > 0`
- 连接质量：`va_webrtc_clients{state="failed"} > 0` 或 `rate(va_webrtc_bytes_sent_total[1m]) == 0 and va_webrtc_clients{state="connected"} > 0`
- 时延：`histogram_quantile(0.95, sum(rate(va_frame_latency_ms_bucket[5m])) by (le,stage)) > 100`

---

## 前端与工具侧

- Web 前端：默认 INFO；ICE/候选等冗长日志降级 debug + 限流（每 1s 汇总 stats）。
- webrtc_file_test：统一 `[tool.webrtc]` 前缀；默认 INFO；`--verbose` 开 DEBUG。

---

## 实施步骤与里程碑

### Phase 0（1 天）：代码扫描与命名映射

- 盘点现有 `VA_LOG_*` 使用点；标注高频日志（逐帧 send/decode）。

### Phase 1（2–3 天）：Logger 能力增强

- 扩展 `core/logger.hpp`：
  - 级别枚举统一、模块 component 字段、`EVERY_N/THROTTLED/ONCE` 宏、JSON 格式、文件轮转。
  - 环境变量解析与默认策略；线程安全与性能评估。

### Phase 2（2–3 天）：模块接入与限流

- 改造 webrtc/encoder/source/analyzer 关键日志：统一前缀、降级 DEBUG、加限流。
- 保留每秒聚合诊断，移除逐帧 INFO。

### Phase 3（2–3 天）：Metrics 注册与 /metrics

- 引入轻量 Registry；封装 Metrics 工具类。
- 在 pipeline/encoder/source/webrtc 注入计数器与直方图；新增 `/metrics` 路由。

### Phase 4（1–2 天）：REST 动态开关

- 新增 `POST /api/logging/set`（全局/模块级别、格式、限流）；`GET /api/logging`（当前配置）。

### Phase 5（1 天）：文档与默认策略

- 增加 `docs/LOGGING.md` 与 `docs/METRICS.md`（规范、使用、FAQ）。
- 默认 Release：`INFO`、text 格式、关键聚合日志开启；`DEBUG` 全部限流或关闭。

---

## 接口与配置（汇总）

- 环境变量：
  - `VA_LOG_LEVEL=info`
  - `VA_LOG_MODULE_LEVELS=transport.webrtc:debug,encoder.ffmpeg:info`
  - `VA_LOG_FORMAT=text|json`
  - `VA_LOG_FILE=logs/video-analyzer.log`
  - `VA_LOG_ROTATE_MB=50`，`VA_LOG_ROTATE_FILES=5`
  - `VA_METRICS=on|off`，`VA_METRICS_VERBOSE=on|off`
- REST：
  - `POST /api/logging/set`，`GET /api/logging`
  - `GET /metrics`

---

## 验收标准

- Release 默认运行 10 分钟，日志量 < 1MB，无逐帧 INFO 刷屏。
- 切换 DEBUG 后，仍有节流（预期 < 10MB/10 分钟，具体看限速）。
- `/metrics` 可被 Prometheus 抓取；关键指标随负载变化。
- 按告警规则可触发/恢复（模拟低 FPS、丢帧、编码 eagain）。

