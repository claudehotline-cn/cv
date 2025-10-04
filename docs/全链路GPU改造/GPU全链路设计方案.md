核心目标：**在不推翻现有结构的前提下，把数据面统一成可承载 Host/GPU 的视图，并逐步把解码→预处理→推理→后处理→渲染→编码搬到 GPU**；仅在必要时回退到 CPU。

------

## 结论（先说人话）

- 你的分层非常契合我们现在的代码结构：
  - **MemoryHandle / FrameSurface / TensorView** 可以直接落在 `core/utils.hpp` 与 `analyzer/interfaces.hpp`，对上层（`Pipeline`/`TrackManager`）不破坏。
  - **BufferPool** 以组件形式放在 `core/`，被 `media/source`（NVDEC）、`analyzer/preproc`（NPP/CV-CUDA）、`engine_ort`（IOBinding）、`media/encoder`（NVENC）共用。
- 关键技术点与坑：
  - **NVDEC/NVENC** 的像素格式、行对齐和 hwframes 上下文要处理好；NVENC 接受 NV12/P010 的设备面更高效。FFmpeg 的 HW 加速/frames ctx 文档和 NV 编码文档是“唯一可信”参考。[FFmpeg+5FFmpeg Trac+5NVIDIA Docs+5](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)
  - **NV12 颜色/缩放在 NPP 上有限**（NV12→RGB 有现成 API，但对 NV12 的直接 resize 支持薄弱，通常做“NV12→RGB(或YUV420)→Resize→回转”或用 CV-CUDA/NvBufSurfTransform），这是成熟方案里普遍采取的折中。[NVIDIA Developer Forums+4NVIDIA Docs+4NVIDIA Docs+4](https://docs.nvidia.com/cuda/archive/10.1/npp/group__nv12torgb.html?utm_source=chatgpt.com)
  - **ONNX Runtime I/O Binding** + **CUDA EP** 是把模型 I/O 留在 GPU 的关键（并可挂接自定义 stream）；官方明确推荐这一路径。[ONNX Runtime+1](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
  - **CUDA Stream + pinned host 内存**：异步 memcpy、跨节点同步、零拷贝路径的稳定性要靠 pinned/registered host memory 与正确的流同步。[HPC ADMINTECH+4NVIDIA Docs+4NVIDIA Docs+4](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/?utm_source=chatgpt.com)

------

## 具体落点（对照你现有目录）

### 1) `core/`：数据模型与 Buffer 池

**新增/替换 `core/utils.hpp` 的数据结构：**

- `MemoryLocation { Host, Device /*未来: NVDEC, NVENC, DMA-BUF...*/ }`
- `Format { NV12, P010, BGR24, RGB8, RGBA32F, FP16_NCHW, ... }`
- `struct MemoryHandle {`
   `void* host_ptr; CUdeviceptr device_ptr; size_t bytes; size_t pitch; int width; int height;`
   `cudaStream_t stream; MemoryLocation location; Format format; /*ref计数/共享所有权*/`
   `bool ensureHost(); bool ensureDevice();`
   `}`
- `struct FrameSurface { MemoryHandle handle; double pts_ms; int width, height; /*色彩空间/stride可选*/ };`
- `struct TensorView { MemoryHandle handle; std::vector<int64_t> shape; /*layout/strides/dtype*/ };`

> 评估：把旧 `Frame{std::vector<uint8_t> bgr}` 逐步替换为 `FrameSurface`，但**短期保留适配层**（见迁移计划）。
>  依据：NVDEC/NVENC/FFmpeg HWFrames 的设备帧都有 pitch、对齐和像素格式约束；用 `MemoryHandle` 才能无损描述这些元信息。[FFmpeg Trac+2FFmpeg+2](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)

**Buffer 池（`core/` 新增 `buffer_pool.\*`）：**

- `GpuBufferPool`：预分配若干 NV12 surface、模型输入/输出 tensor buffer（设备端），`acquire()/release()`；归还前可在 owning stream 上 `cudaEvent`/`cudaStreamSynchronize`。
- `HostBufferPool`：可选使用 pinned host 内存，加速 H2D/D2H 异步传输或回退路径。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)

### 2) `media/source`：NVDEC 解码直接产 GPU 面

- 新增 `SwitchableRtspSourceCuda`（保留原 `SwitchableRtspSource` 做 CPU 回退）。
- FFmpeg 侧：
  - 创建 CUDA `AVHWDeviceContext` + `AVHWFramesContext`（像素格式 = `AV_PIX_FMT_CUDA`，底层 NV12/P010）。
  - `avcodec_send_packet/receive_frame` 取到**设备帧**；把 `AVFrame->data/linesize` + `hwframes` 元信息映射到 `MemoryHandle{ device_ptr, pitch, w, h, format=NV12 }`。
  - 若遇到滤镜或 CPU 路径，则 `ensureHost()` 映射/拷回。
  - 关键点：FFmpeg 的 HWAccelIntro、`nvdec.c`/`hwcontext_cuda.c` 说明了 frames ctx 的使用与 NVENC/NVDEC 的像素/对齐差异（如 U/V 平面顺序/对齐细节）。[FFmpeg Trac+2FFmpeg+2](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)

### 3) `analyzer/preproc`：GPU 颜色/缩放与张量化

- 新增 `LetterboxPreCUDA`：
  - 输入 `FrameSurface(NV12 on Device)`；
  - NV12→RGB/BGR：NPP 或 CV-CUDA 实现（NPP 有 NV12→RGB/BGR 的 API；NV12 直接 resize 支持缺失时用转换→resize→再转的链路）；
  - Normalize + NCHW/FP16/FP32 tensor 写入 **TensorView(handle=Device)**；
  - **避免 NV12→Host**，全程在 device。[NVIDIA Docs+2NVIDIA Docs+2](https://docs.nvidia.com/cuda/archive/10.1/npp/group__nv12torgb.html?utm_source=chatgpt.com)

> 说明：社区和官方渠道都指出 **NPP 对 NV12 的直接 resize 支持有限**；工业界常用套路是**色彩转换后再 resize**，或用 **CV-CUDA/NvBufSurfTransform** 这类更靠近多媒体栈的运算库。[NVIDIA Developer Forums+2NVIDIA Developer Forums+2](https://forums.developer.nvidia.com/t/scale-nv12-images-using-npp-or-other-gpu-methods/60676?utm_source=chatgpt.com)

### 4) `analyzer/engine_ort`：ONNX Runtime + I/O Binding

- 你的 `OrtSession` 改为接收 **`TensorView(handle=Device)`**；
- 使用 **CUDA/TensorRT EP**，并启用 **I/O Binding** 将输入/输出**绑定到设备 tensor**；如果你有用户自建 stream，ORT 官方也支持把 user compute stream 传给 CUDA EP（避免跨流同步）。[ONNX Runtime+1](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)

### 5) `analyzer/postproc`：GPU/CPU 二选一

- YOLO/DETR 后处理可先保留 CPU 实现；性能敏感时再上 GPU kernel。
- 如果选择 GPU 版 NMS/掩码合成，`ModelOutput` 可先存储**设备端中间结果**，渲染/编码阶段再决定是否 `ensureHost()`。
- （可选）给 `IPostprocessor` 增加返回 `DetectionBuffer{ MemoryHandle device/host }` 的重载。

### 6) `analyzer/renderer`：GPU 叠加（可选）

- 若要**全链路 GPU**，渲染器在设备端把框/掩码写回 NV12/BGR（注意行对齐/色域）；否则调用 `ensureHost()` 用现有 CPU 画图。
- 这一步与 NVENC 直连收益很大，省了一次 D2H/H2D 往返。

### 7) `media/encoder`：NVENC 直接吃 GPU surface

- 新增 `FfmpegH264EncoderCuda` 或原类加分支：
  - 优先让编码器接受 **NV12/P010 的 device 面**（对 NVENC 友好）；
  - 如前置链路在 RGB，则在 GPU 侧 RGB→YUV420/NV12（NPP 不直转 NV12 时，可转 YUV420 再拼 NV12，或用 CV-CUDA/自定义 kernel）。NVENC 官方文档 + FFmpeg NVENC 资料是最佳实践参考。[NVIDIA Docs+2NVIDIA Docs+2](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/index.html?utm_source=chatgpt.com)

------

## 与现有接口的“最小侵入式”改造

> 目标：**不推倒**接口，逐步把 `Frame` → `FrameSurface`，把 `std::vector<uint8_t>` → `MemoryHandle`。

**阶段 A（兼容过渡）**

- `IFrameSource::grab(Frame& out)` 保留；新增重载 `grab(FrameSurface& out)`，或在 `Frame` 内嵌 `optional<MemoryHandle>`。
- `IPreprocessor::run(const Frame&, TensorView&, LetterboxMeta&)` → 新增重载接收 `FrameSurface`；
- `IEncoder::encode(const Frame& in, ...)` → 新增 `encode(const FrameSurface& in, ...)`；
- `Analyzer` 内部优先走 GPU 路径，拿不到 `device_ptr` 时调用 `ensureDevice()`（可自动 D2H/H2D）。

**阶段 B（稳定后收口）**

- 把所有数据面签名切到 `FrameSurface/TensorView`；
- 旧 `Frame` 的路径作为回退适配层保留一版（或删掉）。

------

## 路线图（3 个里程碑）

**M1：推理侧“先上 GPU”**

1. 引入 `MemoryHandle/FrameSurface/TensorView/BufferPool`；
2. `OrtSession` 开启 **CUDA/TensorRT EP + I/O Binding**；预处理先走 CPU 版，但把推理 I/O 留在设备（为后续打地基）。[ONNX Runtime+1](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)

**M2：解码与预处理搬到 GPU**

1. 上 **NVDEC**（`SwitchableRtspSourceCuda`），直接产 **设备帧**（NV12/P010）；
2. 预处理上 **NPP/CV-CUDA** 做 NV12→RGB/BGR、letterbox、normalize，产 **Device Tensor**；
3. 保持后处理/渲染/编码原状（可仍在 CPU），验证端到端时延已明显下降。[FFmpeg Trac+2FFmpeg+2](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)

**M3：渲染与编码也上 GPU（全链路）**

1. 渲染器写设备面（最好写回 NV12/BGR）；
2. 编码切 **NVENC** 直接吃 **Device NV12**；在 RGB 链路上补充 GPU 颜色回转。[NVIDIA Docs+1](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/index.html?utm_source=chatgpt.com)

------

## 关键风险与对策（按模块）

- **NV12 处理链**：NPP 对 NV12 的直接 resize 支持有限（官方/社区反复提到），可采用**NV12→RGB/BGR→Resize→回转**或选 **CV-CUDA/NvBufSurfTransform**。提早定路径，避免来回改。[GitHub+2NVIDIA Developer Forums+2](https://github.com/NVIDIA/VideoProcessingFramework/issues/41?utm_source=chatgpt.com)
- **行对齐 & 平面顺序**：NVENC/NVDEC 在 chroma 对齐与 UV 平面顺序上与 FFmpeg 内部约定略有差异，务必按 `hwcontext_cuda.c` 的说明处理；否则编码会异常或花屏。[FFmpeg](https://ffmpeg.org/doxygen/7.0/hwcontext__cuda_8c_source.html?utm_source=chatgpt.com)
- **I/O Binding 正确性**：确保输出缓冲预分配在设备端并绑定；不然 ORT 可能隐式回落到 Host。官方 I/O Binding 文档给出 C++ 侧的绑定范式。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
- **流同步**：节点边界使用事件/流等待；必要时在归还 buffer 前做 `cudaStreamSynchronize` 或 `cudaStreamWaitEvent`。[HPC ADMINTECH+1](https://www.hpcadmintech.com/wp-content/uploads/2016/03/Carlo_Nardone_presentation.pdf?utm_source=chatgpt.com)
- **回退策略**：`ensureHost()/ensureDevice()` 要配合 **pinned host**（`cudaHostAlloc/cudaHostRegister`）以维持带宽与异步语义。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)

------

## 性能要点清单（上线前自检）

- **解码→预处理**：NVDEC 直接产设备面；第一步就避免 D2H。[FFmpeg Trac](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)
- **预处理**：NPP/CV-CUDA 在设备执行；合并色彩与 resize 操作减少读写。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/npp/image_color_conversion.html?utm_source=chatgpt.com)
- **推理**：开启 **CUDA/TensorRT EP + I/O Binding**，必要时绑定**用户 stream**。[ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html?utm_source=chatgpt.com)
- **后处理/渲染**：尽量在 GPU；确需 Host 时使用 pinned 回退。[图灵大学科学与技术学院](https://turing.une.edu.au/~cosc330/lectures/cuda_samples_old/samples/0_Simple/simpleZeroCopy/doc/CUDA2.2PinnedMemoryAPIs.pdf?utm_source=chatgpt.com)
- **编码**：优先 NVENC 直接吃 **Device NV12/P010**；减少临时格式往返。[NVIDIA Docs+1](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/index.html?utm_source=chatgpt.com)

------

## 和你现有目录/接口的“对齐示例”（签名建议）

- `media/source.hpp`
   `virtual bool grab(FrameSurface& out) = 0; // 新`
   `virtual bool grab(Frame& out) = 0;       // 旧，过渡保留`
- `analyzer/interfaces.hpp`
   `virtual bool run(const FrameSurface& in, TensorView& out, LetterboxMeta& meta) = 0; // 新`
   `virtual bool run(const Frame& in, TensorView& out, LetterboxMeta& meta) = 0;        // 旧`
- `engine_ort.hpp`
   `bool run(const TensorView& in_dev, std::vector<TensorView>& out_dev); // I/O Binding`
- `media/encoder.hpp`
   `bool encode(const FrameSurface& in, std::vector<EncodedChunk>& out); // NVENC 首选`

