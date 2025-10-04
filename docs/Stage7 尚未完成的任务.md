# Stage 7 尚未完成的任务

本清单用于跟踪 GPU 全链路改造阶段（Stage 7）仍待完成的事项，并在每次迭代后更新进展。

- 目前 `device_binding_active` 只能反映推理阶段的绑定状态，尚未形成端到端的 GPU 缓冲传递。
- 需要在 Pipeline → Analyzer → Renderer → Encoder 全链路统一使用 `FrameSurface`/`MemoryHandle`，避免强制拷贝回 Host。
- 预处理阶段必须输出 GPU Tensor，并在 ONNX Runtime 中完成设备侧输入/输出绑定，妥善处理 IoBinding 生命周期与同步。
- 任一环节失败时，应自动切换到 CPU 路径并记录详细日志，确保可追溯。
- ✅ **最新进展**：
  - `MemoryHandle::ensureHost/ensureDevice` 已支持 CUDA 拷贝并使用 shared_ptr 管理缓冲所有权。
  - `HostBufferPool`/`GpuBufferPool` 已能复用锁页内存与显存，为零拷贝链路提供基础缓冲管理。
  - 新增 `NvdecRtspSource`（FFmpeg + NVDEC）实现，现已可使用硬件解码获取帧，输出 GPU `FrameSurface`（NV12 缓冲可复用）并回退到 BGR 数据，为后续纯 GPU 渲染与 NVENC 链路铺路。
  - `LetterboxPreprocessorCUDA` 引入 CPU fallback 复用，统一走 Analyzer 管线；后续需将预处理逻辑迁移到 GPU 并生成真正的 CUDA Tensor。
  - 下一步需将这些缓冲池接入 Pipeline/Analyzer，替换现有的逐帧分配逻辑，并继续推进 NVDEC/NVENC 管线。
  - `NvencH264Encoder` 接入工厂，优先启用 NVENC（FFmpeg h264_nvenc），失败时自动回退到 CPU encoder。
  - Ort IoBinding 输出已支持按需禁用 host staging，TensorView.handle 直接携带设备指针，并可按需开启 host 缓冲池；后续需把 Tensor 缓冲池全链路接入
  - GPU NVDEC 源已接入 GpuBufferPool，帧释放时自动归还设备内存，后续可在 NVENC 端继续复用输出缓冲
，TensorView.handle 直接携带设备指针，后续可通过 ensureHost() 在 CPU 回退时复制
  - TODO: GPU YOLO 后处理稳定后，将 CPU/GPU 版本拆分为独立 IPostprocessor 实现，并由工厂按配置选择

## 2. WHIP / WHEP 传输扩展
- `transport_whip.*` 仍为占位实现，尚未接入真实信令或媒体通道。
- 需要基于《代码结构.md》中的接口规范，实现符合 `ITransport` 的 WHIP/WHEP 传输类，并与现有 WebRTC DataChannel 路径隔离。
- 配置层面应允许声明 WHIP/WHEP，但默认保持关闭状态，待链路稳定后再启用。

## 3. 自动化测试与压测
- 目前仅有零散脚本用于冒烟验证，缺少覆盖 GPU/多路流的自动化测试体系。
- 需要编写涵盖模型切换、TensorRT/CUDA 回退、REST API 操作的端到端测试脚本，并纳入流水线或标准操作流程。
- 制定压测方案，验证多路 RTSP、长时间运行场景下的显存/内存占用与回收情况。

## 4. 前端状态展示
- REST 接口已提供 `engine_runtime` 字段，但前端尚未全面消费 GPU 相关信息，也缺乏异常提示。
- 需要在前端补充运行态可视化（执行 Provider、IoBinding、Device Binding、CPU 回退等），并对异常状态给出明显告警与排错指引。

## 5. 日志与可观测性
- GPU 相关日志仍以 Warn/Error 为主，缺少统一的指标上报。
- 需梳理 TensorRT 加载失败、IoBinding 回退、NVDEC/NVENC 出错等关键事件的日志格式，并规划 Prometheus / JSON Metrics 输出，方便外部系统采集。

请结合《GPU 全链路改造方案与规划.md》逐步推进以上事项，并在完成里程碑后同步更新此文件与验收记录。
