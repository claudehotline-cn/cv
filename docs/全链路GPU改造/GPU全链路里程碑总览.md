# 里程碑总览

- **M1：推理侧先上 GPU（最小侵入）**
   目标：引入 MemoryHandle/TensorView 基础抽象；`OrtSession` 开 **CUDA/TensorRT EP**，使用 **I/O Binding**，保证**推理 I/O 全在 GPU**。预处理仍可先走 CPU。[ONNX Runtime+2ONNX Runtime+2](https://onnxruntime.ai/docs/execution-providers/?utm_source=chatgpt.com)
- **M2：解码与预处理搬到 GPU**
   目标：RTSP→**NVDEC** 直接产 **设备面**（NV12/P010）；预处理用 **NPP/CV-CUDA** 做 NV12→RGB/BGR→Normalize/Letterbox→**Device Tensor**；消灭中间 D2H。[GitHub+3FFmpeg Trac+3NVIDIA Docs+3](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)
- **M3：渲染与编码也上 GPU（全链路）**
   目标：在设备端叠加框/掩码；**NVENC** 直接吃 **Device NV12/P010**；只在 fallback 时才触发 Host 映射。[NVIDIA Docs+1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html?utm_source=chatgpt.com)

------

# 公共基础（一次性改动，M1 就完成）

## 1) 新增基础抽象（`core/utils.hpp`）

```
enum class MemoryLocation { Host, Device };
enum class PixelFormat { NV12, P010, BGR24, RGB8, RGBA32F };
enum class DType { U8, F16, F32 };

struct MemoryHandle {
  void*        host_ptr   = nullptr;   // 可为空
  CUdeviceptr  device_ptr = 0;         // 可为0
  size_t       bytes = 0, pitch = 0;
  int          width = 0, height = 0;
  cudaStream_t stream = nullptr;       // 可选绑定流
  MemoryLocation location = MemoryLocation::Host;
  PixelFormat  format = PixelFormat::BGR24;
  bool ensureHost();    // 若在GPU则 D2H（建议用 pinned host）
  bool ensureDevice();  // 若在Host则 H2D（绑定 stream）
};

struct FrameSurface {
  MemoryHandle handle;
  double pts_ms = 0;
  int width = 0, height = 0;
  // 可选：色彩空间/色域/stride
};

struct TensorView {
  MemoryHandle handle;                   // 持有 Device/Host 缓冲
  std::vector<int64_t> shape;            // e.g., {1,3,640,640}
  DType dtype = DType::F32;
  // 可选：Layout/Strides
};
```

- **Pinned host/stream**：`ensureHost/ensureDevice` 内建议使用 **pinned host**（`cudaHostAlloc/cudaHostRegister`）+ 指定 **cudaStream** 做异步传输与同步。[NVIDIA Docs+2developer.download.nvidia.com+2](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)

## 2) Buffer 池（`core/buffer_pool.*`）

- `GpuBufferPool`：预分配 NV12 surface、模型输入/输出 tensor 的 **Device** 缓冲；`acquire()`/`release()`；归还前做事件/流同步（`cudaEventRecord/StreamWaitEvent` 或 `cudaStreamSynchronize`）。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__STREAM.html?utm_source=chatgpt.com)
- `HostBufferPool`：可选 pinned host 池，供 fallback/边界转换用。[NVIDIA Docs](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)

> 接口不依赖具体库，便于在 `media/`、`analyzer/`、`engine_ort/` 之间共用。

------

# M1：推理侧先上 GPU（最小侵入）

## 代码改动

**文件与接口**

- `analyzer/interfaces.hpp`

  - 给 `IPreprocessor::run` 添加**新重载**（不破坏旧签名）：

    ```
    virtual bool run(const FrameSurface& in, TensorView& out, LetterboxMeta& meta) = 0;
    ```

- `analyzer/ort_session.{hpp,cpp}`

  - `bool run(const TensorView& in, std::vector<TensorView>& outs)`：实现 **ONNX Runtime I/O Binding**（输入/输出都绑定 **Device**）。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
  - 构造时按全局设定追加 **CUDA/TensorRT EP**。[ONNX Runtime+1](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html?utm_source=chatgpt.com)

- `core/pipeline.*`

  - `Analyzer` 里优先走 `FrameSurface` 路径；若上游仍返回旧 `Frame`，用兼容层临时填充一个 `FrameSurface` 并 `ensureDevice()`。

**实现步骤**

1. **启用 CUDA/TensorRT EP**（选其一起步）：
   - `Ort::SessionOptions so;`
   - `OrtSessionOptionsAppendExecutionProvider_CUDA(so, opts)` 或 `...TensorRT(so, trt_opts)`。[ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html?utm_source=chatgpt.com)
   - EP 列表优先级如 `["CUDAExecutionProvider","CPUExecutionProvider"]`。[ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/?utm_source=chatgpt.com)
2. **I/O Binding**：
   - `Ort::IoBinding io(sess);`
   - 将 `TensorView.handle.device_ptr` 包装为 `Ort::Value`（CUDA 设备内存），`io.BindInput(name, device_tensor)`；
   - 为每个输出预分配 **Device** 缓冲并 `BindOutput`；`sess.Run(run_opts, io)`；
   - 运行完把绑定的 Device 输出**映射回** `TensorView(handle=Device)`。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
3. **同步与错误处理**：
   - 如果你使用**自定义 cudaStream**，按 ORT CUDA EP 文档把 stream 传入 provider options/RunOptions，避免跨流同步。[ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html?utm_source=chatgpt.com)
   - 任何 Host 输出请求都意味着一次 D2H（ORT 会自动做），务必**显式预绑定** Device 输出以避免隐式拷贝。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)

**验收标准**

- 运行一次端到端：预处理仍 CPU；推理完成后**不出现 Host 拷贝**（从 profiler/日志确认）；IOBinding 生效（输出在 Device）。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
- `/model/switch` 后首次 Run 成功，且切换延迟在期望范围内（已做预热）。

**回滚点**

- 若遇到驱动/EP 问题，可把 EP 恢复为 `CPUExecutionProvider`，I/O Binding 关闭；功能保持可用。[ONNX Runtime](https://onnxruntime.ai/docs/execution-providers/?utm_source=chatgpt.com)

------

# M2：解码与预处理搬到 GPU

## 代码改动

**媒体源：`media/source_switchable_rtsp.{hpp,cpp}`**

- 新增 `SwitchableRtspSourceCuda`（或在现类中添加 CUDA 分支）：
  - 创建 `AVHWDeviceContext` (CUDA) 与 `AVHWFramesContext`；解码输出为 **AV_PIX_FMT_CUDA**（底层 NV12/P010）。
  - 循环 `avcodec_send_packet/receive_frame` 拿到 **设备帧**；将 `AVFrame` 映射为 `MemoryHandle{device_ptr,pitch,w,h,location=Device,format=NV12}` 返回 `FrameSurface`。[FFmpeg+1](https://www.ffmpeg.org/doxygen/4.1/group__lavc__encdec.html?utm_source=chatgpt.com)
  - 若需要 CPU 路径，调用 `FrameSurface.handle.ensureHost()`。
  - 参考资料：FFmpeg **HWAccelIntro**、NVDEC 编程指南、FFmpeg 发送/接收 API 文档。[FFmpeg Trac+2NVIDIA Docs+2](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)

**预处理：`analyzer/preproc_letterbox_cuda.{hpp,cpp}`**

- 输入：`FrameSurface`（**Device NV12**）。
- 使用 **NPP**（或 **CV-CUDA**）完成：
  1. NV12 → RGB/BGR（`nppiNV12ToRGB_*` 族函数）。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/archive/11.0/npp/group__nv12torgb.html?utm_source=chatgpt.com)
  2. Resize/Letterbox + Normalize → 写入 **TensorView(handle=Device)**。
- 注意：**NPP 不直接支持 NV12 resize**，常用做法是**先色彩转换再 resize**（或用 CV-CUDA/NvBufSurfTransform 实现一体化处理）。[GitHub](https://github.com/NVIDIA/VideoProcessingFramework/issues/41?utm_source=chatgpt.com)

**接口联动**

- `IPreprocessor::run(const FrameSurface&, TensorView&, LetterboxMeta&)` 在 CUDA 实现里直接返回 **Device Tensor**；Analyzer 后续链路不落地到 Host。

**同步与错误处理**

- 预处理核与解码的 **cudaStream**：
  - 在 `MemoryHandle.stream` 记录当前流，预处理可在同一流上继续，或在新流上启动并用事件同步。[NVIDIA Docs](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__STREAM.html?utm_source=chatgpt.com)
- 如果色彩转换/resize 失败，触发回退：`ensureHost()` → 走原 CPU 预处理（保命路径）。

**验收标准**

- 解码帧 `FrameSurface.handle.location == Device`。
- 预处理输出 `TensorView.handle.location == Device`。
- M1 的 I/O Binding 继续生效，推理无需 D2H/H2D。
- **NV12→RGB** 路径经 NPP 或 CV-CUDA 正常工作，像素正确（抽检对比 CPU 版）。[NVIDIA Docs](https://docs.nvidia.com/cuda/archive/11.0/npp/group__nv12torgb.html?utm_source=chatgpt.com)

------

# M3：渲染 + 编码 上 GPU（全链路）

## 代码改动

**渲染器（可选 GPU 版）**

- 新增 `renderer_gpu.*`：在设备端将框/掩码叠加到 **NV12/BGR** Surface（需注意 pitch/对齐/色域）。
- 若暂不做 GPU 渲染，保留 CPU 渲染，但在编码前把渲染结果转回 **Device NV12**（避免 NVENC 再次 H2D）。

**编码器：`media/encoder_h264_ffmpeg.{hpp,cpp}` 扩展 NVENC 路径**

- 优先选择 **NVENC**，让编码器直接接受 **Device NV12/P010** Surface：
  - 在 FFmpeg 里用 HWFramesCtx 与 NVENC 绑定（避免多余拷贝）；
  - 仍然沿用 `avcodec_send_frame/receive_packet` API（send/receive 模式）。[FFmpeg](https://www.ffmpeg.org/doxygen/4.1/group__lavc__encdec.html?utm_source=chatgpt.com)
- 参考：**NVIDIA NVENC 编程指南** 和 “FFmpeg with NVIDIA GPU acceleration”。[NVIDIA Docs+1](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html?utm_source=chatgpt.com)

**同步与错误处理**

- 编码前确保绘制完成（同一流或事件同步）；
- 回退：若 NVENC 不可用，`ensureHost()` → 走 x264（低一档性能，但保证功能）。
- 注意 NVENC/NVDEC 的像素对齐/UV 顺序细节与 HWFramesCtx 设置；按 FFmpeg 的 HWAccel 指南配置。[FFmpeg Trac](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)

**验收标准**

- 解码→预处理→推理→（可选 GPU 渲染）→编码 **全在 GPU**；
- 性能瓶颈不再是 H2D/D2H；数据面统计的 Host↔Device 次数显著下降；
- NVENC 输出码流正确（播放器/比特流分析通过）。[NVIDIA Docs](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html?utm_source=chatgpt.com)

------

# 接口“增量式”调整建议（不破坏旧代码）

- **阶段 A（M1）**：仅**新增**重载/类型，不删旧接口
  - `IFrameSource::grab(FrameSurface& out)`（新增）
  - `IPreprocessor::run(const FrameSurface&, TensorView&, LetterboxMeta&)`（新增）
  - `IEncoder::encode(const FrameSurface&, vector<EncodedChunk>&)`（新增）
  - `OrtSession::run(const TensorView&, vector<TensorView>&)`（实现 I/O Binding）
- **阶段 B（M2/M3 完成后）**：**收口**
  - 将上游默认路径切到 `FrameSurface/TensorView`；旧 `Frame` 路径作为 fallback/测试保留或移除。

------

# 错误处理与同步的一页纸

- **FFmpeg send/receive 的语义**：
  - 解码：`avcodec_send_packet` / `avcodec_receive_frame`；
  - 编码：`avcodec_send_frame` / `avcodec_receive_packet`；
  - `EAGAIN` 是**正常**的背压信号，继续送/取即可。[FFmpeg+1](https://www.ffmpeg.org/doxygen/4.1/group__lavc__encdec.html?utm_source=chatgpt.com)
- **I/O Binding 的陷阱**：
  - 未绑定输出 → ORT 认为你要在 CPU 拿结果，会**自动 D2H**；务必预分配并绑定 **Device 输出**。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
- **NPP/CV-CUDA 限制**：
  - **NPP 不支持 NV12 直接 resize**，通常要 NV12→RGB/BGR→resize（或用 CV-CUDA）。提前定好路径。[GitHub](https://github.com/NVIDIA/VideoProcessingFramework/issues/41?utm_source=chatgpt.com)
- **Pinned Host/Stream 同步**：
  - Host<->Device 传输建议用 pinned host；跨节点依赖用 `cudaEvent` 或 `cudaStreamSynchronize`，避免隐性同步拖慢流水线。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)

------

# 验收清单（每阶段都要打勾）

- **功能**：不同源/模型/任务切换正常（我们原有 REST 不变）。
- **性能**：
  - M1：推理 I/O 不再发生隐式 D2H/H2D（通过 I/O Binding 诊断与日志确认）。[ONNX Runtime](https://onnxruntime.ai/docs/performance/tune-performance/iobinding.html?utm_source=chatgpt.com)
  - M2：解码帧来自 **Device**；预处理产出 **Device Tensor**；无中间 Host 往返。[FFmpeg Trac](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)
  - M3：编码直接吃 **Device NV12**；全链路 GPU。[NVIDIA Docs](https://docs.nvidia.com/video-technologies/video-codec-sdk/13.0/nvenc-video-encoder-api-prog-guide/index.html?utm_source=chatgpt.com)
- **稳定性**：
  - 失败自动回退（Host 路径）；
  - 流/事件同步无死锁；
  - 内存池无泄漏（`acquire/release` 成对）。

------

# 参考资料（关键点）

- **FFmpeg send/receive API（编解码）**：官方 doxygen（解/编）与概述。[FFmpeg+1](https://www.ffmpeg.org/doxygen/4.1/group__lavc__encdec.html?utm_source=chatgpt.com)
- **FFmpeg 硬件加速总览 / NVENC & NVDEC**：HWAccelIntro。[FFmpeg Trac](https://trac.ffmpeg.org/wiki/HWAccelIntro?utm_source=chatgpt.com)
- **NVDEC/NVENC 编程指南**：官方 Video Codec SDK 文档（解码/编码）。[NVIDIA Docs+1](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.2/nvdec-video-decoder-api-prog-guide/index.html?utm_source=chatgpt.com)
- **FFmpeg × NVIDIA GPU 加速指南**（官方）：配置/互操作方法。[NVIDIA Docs](https://docs.nvidia.com/video-technologies/video-codec-sdk/12.0/ffmpeg-with-nvidia-gpu/index.html?utm_source=chatgpt.com)
- **ONNX Runtime CUDA EP & I/O Binding**（官方）：启用 CUDA/TRT、I/O 绑定、图优化/图捕获要点。[ONNX Runtime+2ONNX Runtime+2](https://onnxruntime.ai/docs/execution-providers/CUDA-ExecutionProvider.html?utm_source=chatgpt.com)
- **NPP NV12→RGB**（官方函数族）：`nppiNV12ToRGB_*`。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/archive/11.0/npp/group__nv12torgb.html?utm_source=chatgpt.com)
- **NPP 对 NV12 resize 的限制（社区/官方工程讨论）**：需要转换再 resize。[GitHub](https://github.com/NVIDIA/VideoProcessingFramework/issues/41?utm_source=chatgpt.com)
- **CUDA pinned host / 流管理**：Runtime API 文档。[NVIDIA Docs+1](https://docs.nvidia.com/cuda/cuda-runtime-api/group__CUDART__MEMORY.html?utm_source=chatgpt.com)