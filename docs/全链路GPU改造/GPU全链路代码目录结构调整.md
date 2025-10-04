# GPU 全链路代码目录结构调整

本文件在《代码结构总览》的基础上，突出 Stage 7 以及后续 GPU 改造所需的关键目录与职责划分，确保实现与设计一致。

## 目录树（简化）

```
video-analyzer/
├── config/                      # YAML 配置：模型、任务、引擎、分析参数
├── include/
│   ├── analyzer/
│   ├── core/
│   ├── media/
│   └── server/
├── src/
│   ├── analyzer/                # 预处理 / 推理会话 / 后处理 / 渲染
│   │   ├── interfaces.hpp       # IPreprocessor/IModelSession/... 接口
│   │   ├── analyzer.(hpp|cpp)   # FrameSurface 桥接、参数切换
│   │   ├── preproc_letterbox_cpu/cuda.*
│   │   ├── ort_session.(hpp|cpp)
│   │   ├── postproc_*.cpp       # YOLO / DETR 等任务
│   │   └── renderer_*.cpp       # Stage 7 渲染抽象
│   ├── core/                    # Pipeline、EngineManager、BufferPool 等
│   │   ├── utils.(hpp|cpp)      # Frame / FrameSurface / TensorView
│   │   ├── buffer_pool.(hpp|cpp)# Host/GPU 内存池占位
│   │   ├── pipeline.(hpp|cpp)   # 拉流→分析→编码→传输主循环
│   │   ├── pipeline_builder.*   # 将配置装配为 Pipeline
│   │   └── track_manager.*      # 订阅/切换/资源管理
│   ├── media/                   # 解码、编码、传输
│   │   ├── source_switchable_rtsp.*  # OpenCV/FFmpeg 拉流
│   │   ├── encoder_h264_ffmpeg.*     # 默认 CPU 编码，后续扩展 NVENC
│   │   └── transport_*               # WebRTC DataChannel + WHIP/WHEP 占位
│   ├── server/                  # REST 接口
│   │   └── rest.cpp             # /subscribe /switch /engine 等 API
│   └── composition_root.cpp     # 工厂组装与依赖注入
├── build/                       # CMake 生成产物（Release/Debug）
├── test/                        # 自动化脚本与后端测试
└── model/、data/                # 示例模型/样例资源
```

## Stage 7 调整要点

1. **核心抽象统一**：`core/utils` 负责 `FrameSurface`、`MemoryHandle` 等结构；`buffer_pool` 为 Host/GPU 内存复用预留接口。
2. **Pipeline 桥接**：`core/pipeline` 按阶段逐步从 `Frame` 过渡到 `FrameSurface`，并确保编码/传输仍可回退到 CPU。
3. **推理链路**：`analyzer/` 子目录承载所有 GPU 相关扩展（Letterbox CUDA、Ort IoBinding、CUDA 渲染等）；新增接口必须在 `interfaces.hpp` 中声明，并同步 include/ 目录。
4. **媒体层扩展**：在保留 FFmpeg CPU 路径的同时，为 NVDEC/NVENC、WHIP/WHEP 预留独立实现文件，遵循 `IFrameSource` / `IEncoder` / `ITransport` 接口。
5. **服务层**：REST API 不感知底层介质，只通过 `EngineManager` 汇报运行态（provider、io_binding、device_binding 等）。

后续若目录或职责发生变化，务必同时更新本文件与 `docs/代码结构.md`，以维持文档与代码实现的一致性。
