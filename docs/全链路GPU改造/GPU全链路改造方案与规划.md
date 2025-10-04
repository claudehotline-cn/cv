# GPU 全链路改造方案与规划

本方案用于指导 video-analyzer 项目在 Windows 11 + CUDA 12.9 + TensorRT 10.x 环境下完成端到端 GPU 化改造。目标是在保持 CPU 回退能力的同时，使解码、预处理、推理、后处理、渲染与编码全部可以在显卡上闭环执行，并通过 REST/WebRTC 服务对外输出稳定的视频分析能力。

## 目标与范围
- **GPU 主路径**：NVDEC 解码 → NPP/CV-CUDA 预处理 → ONNX Runtime CUDA/TensorRT 推理 + IoBinding → CUDA 后处理与渲染 → NVENC 编码。
- **CPU 回退**：任何阶段出现异常可以自动回落到现有 CPU 流程；REST、WebRTC、模型管理能力保持不变。
- **扩展性**：保留 WHIP/WHEP 传输接口占位、TensorRT 扩展入口，方便后续能力注入。

## 阶段里程碑
1. **M1：基线稳定** – 引入 MemoryHandle / FrameSurface / TensorView 抽象，IoBinding 运行态可观测；框架仍以 CPU 处理为主。（已完成）
2. **M2：GPU 解码 + 预处理** – 接入 NVDEC，利用 NPP 或 CV-CUDA 构造 GPU Tensor 输入。
3. **M3：GPU 后处理 + 编码** – 迁移 NMS/绘制到 CUDA，实现 NVENC 推流；端到端零拷贝。
4. **M4：压测与鲁棒性** – 多路 RTSP、长稳运行、资源回收、回退策略验证。
5. **M5：收尾与清理** – 移除废弃接口、补充文档/CI、完成知识转移。

## 关键改造模块
- **核心抽象（core）**：MemoryLocation、PixelFormat、MemoryHandle、FrameSurface、TensorView、BufferPool（Host/GPU）。
- **分析链路（analyzer）**：IPreprocessor / IRenderer / IFrameFilter 新增 FrameSurface 重载；OrtModelSession 统一填充句柄信息，支撑 IoBinding。
- **媒体层（media）**：Source/Encoder/Transport 需提供 GPU 友好实现（NVDEC、NVENC、DataChannel 等）。
- **Server/REST**：保持既有 API，不感知底层介质变化，仅通过 runtime 信息暴露状态。

## 迁移顺序
1. **桥接阶段**：Frame ↔ FrameSurface 互通，默认走 CPU，但优先尝试 GPU 重载（当前进度）。
2. **NVDEC 与预处理**：实现 GPU surface 输出，并通过预处理接口下发 TensorView(handle=Device)。
3. **推理增强**：完善 Ort IoBinding，确保 device_binding_active 真实反映显存绑定状态。
4. **后处理 / 渲染**：CUDA NMS、绘制覆盖，输出 FrameSurface；失败时自动回退 CPU。
5. **编码与传输**：NVENC + WebRTC GPU 输出，支持批量推流。

## 目录结构基线
参见《GPU全链路代码目录结构调整.md》。核心层级如下：
- `core/`：内存抽象、缓冲池、公共工具。
- `analyzer/`：预处理、推理会话、后处理、渲染实现。
- `media/`：解码器、编码器、传输实现（含占位的 WHIP/WHEP）。
- `app/`、`server/`、`composition_root/`：配置加载、REST 接口、对象装配。

## 平台与依赖
- **操作系统**：Windows 11 25H2。
- **GPU 栈**：CUDA 12.9、TensorRT 10.x、NVIDIA 驱动 ≥ 581.42。
- **推理框架**：ONNX Runtime 1.23.0（自编译 GPU 版本）。
- **多媒体**：FFmpeg（NVDEC/NVENC 支持）、libdatachannel/ixwebsocket、OpenCV。
- **CMake 选项**：`WITH_CUDA`、`WITH_TRT`、`WITH_NVDEC`、`WITH_NVENC` 等需按阶段启用。

## 验收指标
- **性能**：单路 1080p30 GPU 路径延迟 < 80 ms，CPU 回退占比 < 15%；四路 720p30 长稳运行≥2 小时无内存泄漏。
- **稳定性**：NVDEC/NVENC/Iobinding 出错自动回退，日志清晰记录故障原因；长稳测试不少于 8 小时。
- **观测性**：`engine_runtime` 返回 provider、gpu_active、io_binding、device_binding、cpu_fallback 等状态；Pipeline 暴露 FPS、延迟、丢帧数。

## 风险与缓解
- **依赖缺失**：NPP/CV-CUDA、NV Codec SDK 缺库时，应自动落回 CPU 并提示安装指引。
- **内存管理**：GPU/Host 缓冲池需防止碎片化；引入显式生命周期与引用计数。
- **接口兼容**：REST/WebRTC 不得因 GPU 链路而改变请求/响应格式，保证配置向后兼容。

## 当前进度（2025-10-04）
- Analyzer 已实现 FrameSurface 桥接，预处理、推理、渲染会优先调用 GPU 重载，失败时回退到原有 CPU 代码。
- OrtModelSession 输出统一填充 MemoryHandle 元数据，为后续真正的 GPU 零拷贝铺路。
- Passthrough 渲染器与 CPU Letterbox 预处理已对接新的句柄语义，兼容现有编码流程。

后续任务：在此基础上接入 NVDEC surface、GPU 预处理与 GPU 渲染，实现 Stage 7 “真正的 GPU/IOBinding 管线落地” 目标。
