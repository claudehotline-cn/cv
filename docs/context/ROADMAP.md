# 路线图总览

- M0「GPU 可用 + 基础稳定」
  - 目标：容器 GPU 注入稳定（gpus: all），NVENC 正常，原有 ORT CUDA/ORT‑TRT 可用；多阶段图以相对路径（models/…）。
  - 验收：WHEP 正常出图；`analyzer.ort|trt load ... outputs>0`；无 `libcuda.so.1`/NVENC 报错；Prom 帧数指标递增。

- M1「原生 TensorRT + 异步预热」
  - 目标：tensorrt‑native 读取 .engine 稳定推理；订阅时后台预热，不阻塞返回；开启分析时不再加载。
  - 验收：订阅→日志出现“预热开始/完成”；切到 ON 无新的 open/load；`ms.nms boxes>0`；720p 正常帧率。

- M2「可观测 + 回退 + 基准」
  - 目标：完善诊断日志与指标；必要时回退链（native→ORT‑TRT→CUDA）；提供端到端基准与部署指引。
  - 验收：出现 `pipeline.analyze / ms.runner / ms.node_model / ms.nms` 关键日志；Prom 导出预热/构建耗时；基准报告完成。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| M0 | GPU 注入与 NVENC 修复 | compose `gpus: all`；NVENC `aq-strength` 合法化；相对路径图 | 主机驱动/工具包差异 → 自检清单 | 无异常日志，帧数>0 |
| M1 | 原生 TRT + 异步预热 | tensorrt-native 读取 .engine；订阅后台 open_all；订阅幂等 | 预热与首帧竞争 → 幂等/一次性 open | 切 ON 不再 load；boxes>0 |
| M2 | 可观测/回退/基准 | `pipeline.analyze`/`ms.*` 日志与 Prom；回退链；报告 | 指标不足 → 增加预热/构建/推理耗时 | 报告含 FPS/P95 |

# 依赖矩阵

- 内部依赖：
  - VA（多阶段、NVDEC/Overlay/NMS/NVENC）、CP（订阅/切换/热更）、VSM（源）、Web（WHEP/控制）。
- 外部依赖（库/服务/硬件）：
  - CUDA 12/13、cuDNN 9、TensorRT ≥10.x、ONNX Runtime 1.23.x、FFmpeg、NVIDIA GPU（5090D/SM_120）、MySQL、Redis。

# 风险清单（Top-5）

- NVENC/驱动不匹配 → 启动时报错 → 日志含 `libcuda.so.1`/avcodec 失败 → 统一 `gpus: all` 与自检脚本。
- 原生 TRT 与模型不兼容 → 反序列化失败 → `deserializeCudaEngine failed` → 回退 ORT‑TRT/CUDA，提供 .onnx 旁路。
- 异步预热与首帧竞争 → 二次 open/load → 订阅幂等 + 一次性 open（门闩）+ 引擎缓存。
- 推理有输出但 boxes=0 → 阈值/布局差异 → `ms.nms candidates=0` → 暂降 conf=0.25 验证，必要时补布局开关。
- 观测不足影响定位 → 缺少关键日志/指标 → 仅见 load 无 run → 增补 `pipeline.analyze/ms.runner/ms.node_model/ms.nms` 与 Prom 预热/耗时指标。

