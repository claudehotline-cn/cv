# PromQL Alert Examples

- FPS low per source:
  `sum by (source_id, path) (rate(va_frames_processed_total[1m])) < 10`

- Drop ratio per source:
  `sum by (source_id, path) (rate(va_frames_dropped_total[5m])) / sum by (source_id, path) (rate(va_frames_processed_total[5m])) > 0.1`

- Encoder backpressure spikes:
  `increase(va_encoder_eagain_total[5m]) > 0`

- WebRTC stalled stream:
  `rate(va_webrtc_bytes_sent_total[1m]) == 0 and va_webrtc_clients{state="connected"} > 0`

- P95 latency by stage per source (ms):
  `histogram_quantile(0.95, sum by (le, stage, source_id, path) (rate(va_frame_latency_ms_bucket[5m]))) > 100`

- Pipeline FPS floor:
  `sum by (source_id, path) (va_pipeline_fps) < 10`

