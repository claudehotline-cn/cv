# 基准报告模板（VA/CP/VSM）

- 日期：
- 设备：GPU 型号 / 驱动版本 / CUDA / cuDNN
- 版本：TensorRT / ONNX Runtime / FFmpeg / 镜像标签
- 模型：名称 / 输入尺寸（如 1x3x640x640）/ 精度（FP16/FP32）
- 配置：
  - provider：cuda | tensorrt | tensorrt-native
  - 预热：开启/关闭；并发 cap；超时阈值
  - 缓存：ORT 引擎缓存 / 原生 TRT timing/engine 缓存
  - 编码：分辨率 / FPS / 码率 / 低延迟设置
- 源：RTSP 地址（或说明）/ 分辨率 / FPS

## 结果（单路）

| provider           | FPS  | preproc P50 | preproc P95 | infer P50 | infer P95 | post P50 | post P95 | encode P50 | encode P95 |
|--------------------|------|-------------|-------------|-----------|-----------|----------|----------|------------|------------|
| cuda               |      |             |             |           |           |          |          |            |            |
| tensorrt           |      |             |             |           |           |          |          |            |            |
| tensorrt-native    |      |             |             |           |           |          |          |            |            |

- 加载/预热：
  - `va_model_session_load_seconds_count/sum`：
  - `va_graph_open_duration_seconds_count/sum`：
  - 失败计数：`va_model_session_load_failed_total` / `va_graph_open_failed_total`

## 观察与结论

- 吞吐：
- 延迟：
- 热启：
- 建议：

