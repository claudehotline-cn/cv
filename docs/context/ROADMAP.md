# 路线图总览

- M0「GPU 可用 + 基础稳定」
  - 目标：Compose GPU 注入稳定（gpus: all），NVENC 正常；ORT CUDA/ORT‑TRT 可用；多阶段图以相对路径（models/…）。
  - 验收：WHEP 正常出图；无 /NVENC 报错；Prom 帧数指标递增。

- M1「原生 TensorRT + 预热 + 回退链」
  - 目标：tensorrt‑native 读取 .engine 稳定推理；订阅后台预热；落地 Provider 回退链（TRT→Triton→ORT‑TRT→CUDA）。
  - 验收：订阅→日志出现“预热开始/完成”；切至 ON 无二次 load；；720p 正常帧率；回退链在上游不可用时自动生效。

- M2「可观测 + Triton 集成 + 基准」
  - 目标：完善直方图与失败计数（加载/预热/分段）；接入 Triton gRPC（T0 Host 内存，后续 CUDA SHM）；提交基准报告。
  - 验收：出现 、、、；基准报告含 FPS/P95。

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
| ---- | ---------- | -------- | --------- | -------- |
| M0 | GPU 注入与 NVENC 修复 | compose gpus:all；NVENC 合规；相对路径图 | 主机驱动不匹配→自检清单 | 帧数>0、无报错 |
| M1 | TRT + 预热 + 回退 | tensorrt-native；open_all 并发/超时；回退链 | 预热与首帧竞争→幂等 open | boxes>0、720p 正常 FPS |
| M2 | 可观测与 Triton | 会话/预热/分段直方图；Triton gRPC T0；基准 | 指标不足→补采样与节流 | 报告含 FPS/P95 |

# 依赖矩阵

- 内部依赖：
  - VA（多阶段、NVDEC/NMS/Overlay/NVENC）、CP（订阅/切换/系统信息聚合）、VSM（源）、Web（WHEP/控制）。
- 外部依赖（库/服务/硬件）：
  - CUDA 12/13、cuDNN 9、TensorRT ≥10.x、ONNX Runtime 1.23.x、Triton Server、FFmpeg、NVIDIA GPU（SM_120）、MySQL、Redis。

# 风险清单（Top-5）

- 驱动/工具链不匹配 → 启动时报错（libcuda/NVENC） → 日志异常/容器退出 → 统一使用 gpus:all + 版本自检。
- 引擎/模型不兼容（TRT/Triton） → 反序列化/Infer 失败 → /RPC 失败 → 回退链 TRT→ORT→CUDA，打印失败指纹。
- 异步预热与首帧竞争 → 二次 open/load → 限制并发 + 幂等 open + 引擎缓存。
- 推理输出 boxes=0 → 阈值/布局差异 → /boxes=0 → 临时降低 conf 验证，必要时补布局开关。
- 可观测不足 → 仅见 load 无 run → 增补  节流日志与四类直方图（加载/预热/分段/Triton）。

