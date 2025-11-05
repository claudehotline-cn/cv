# 路线图总览

- M0「GPU 链路稳定 + ORT 固化」：容器内源码编译 ORT v1.23.2（SM=90;120），补全动态库链接；默认开启零拷贝与统一 CUDA 流；前端提示修复。
  - 验收：`provider=cuda` 时 `ort.run outputs>0`、`ms.node_model out_count>0`；日志含 in/out 与 shapes；Prom 帧数指标递增。
- M1「TensorRT‑RTX EP 接入」：完善 ORT EP 选择（tensorrt-rtx→tensorrt→cuda），在 5090D 上优先解析 RTX EP 并回退有序。
  - 验收：`analyzer.ort load` 显示 resolved=`tensorrt-rtx`（或 `tensorrt`），端到端 outputs>0；720p ≥30FPS；不劣于 CUDA EP。
- M2「原生 TensorRT 会话」：实现 `TensorRTModelSession`（FP16/静态 1x3x640x640），统一流与设备视图输出；规划动态 profile/引擎序列化。
  - 验收：provider=`tensorrt-native` 时 outputs>0；与 ORT EP 行为一致；压测性能达标（720p ≥30FPS）。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| P0 | ORT 构建固化 | cudnn-devel 构建；ORT 1.23.2 源码；SM=90;120；并行24；修复 SONAME | 链接缺失→补软链；ARG 泄漏→阶段内声明 | 构建成功；VA 启动健康 |
| P1 | EP 选择完善 | tensorrt-rtx→tensorrt→cuda 有序回退；选项映射 | TRT 不可用→回退 CUDA，打印告警 | 输出>0；日志 provider 正确 |
| P2 | 原生 TRT 会话 | TensorRT 解析/构建/绑定；统一 CUDA 流；设备视图输出 | 形状/类型不匹配→限制首版 float32；后续适配 | 720p ≥30FPS；零拷贝稳定 |
| P3 | 动态/序列化 | 动态 profile；plan 缓存；预热 | 存储/兼容性→版本封存与哈希 | 冷启动<3s；回归稳定 |
| P4 | 可观测/自动化 | 指标完善；CP 脚本；故障注入 | 采集不足→补日志/指标 | 5 分钟出具端到端证据 |

# 依赖矩阵

- 内部依赖：
  - VA（analyzer/multistage、ORT/TRT 会话、CUDA 预处理/叠加、NMS）、CP（订阅/切换/换模）、VSM（RTSP 源）、Web（交互与播放）。
- 外部依赖（库/服务/硬件）：
  - CUDA 12.9、cuDNN 9.x、TensorRT ≥10.3（5090D/SM_120）、ONNX Runtime 1.23.2、FFmpeg、NVIDIA GPU（RTX 5090D）、MySQL、Redis。

# 风险清单（Top-5）

- 模型无 Graph 输出 → 导出异常/权重分片缺失 → `outputs=0`/load 错 → 使用 `nms=False` 的 ONNX；补齐 external data。
- TRT 版本不兼容 → EP 失败/回退 → 加载日志/EP 错误 → 固定 TRT 版本，提供回退链路 → 首选 RTX EP，不可用即退。
- 零拷贝链路不一致 → NMS 读取失败 → `on_gpu=false` 或 `stage_device_outputs=true` → 默认 device_output_views；关闭 stage。
- ORT/库链接缺失 → 构建/复制遗漏 → ldd 缺少 onnxruntime → 软链与校验清单，强制无缓存构建。
- 前端提示与交互问题 → 误引导/乱码 → 浏览器消息/日志 → 统一 UTF‑8，修复固定文案；回归测试。
