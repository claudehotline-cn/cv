# 项目上下文（2025‑11‑07｜VA/CP/VSM/Web + Docker + TensorRT）

本文汇总当前实现状态与关键决策，仅描述“已落地”的能力与配置，便于排障与扩展。

## 一、架构与数据流
- VA：RTSP 拉流 → 预处理（NVDEC→CUDA Letterbox） → 推理（ORT CUDA/ORT‑TRT/原生 TensorRT） → 后处理（YOLO NMS：GPU/CPU） → 叠加（CUDA） → 编码（NVENC） → WHEP。
- CP：对外 REST（/api/subscriptions、/api/control/pipeline_mode、/api/control/hotswap），代理 WHEP；VSM：RTSP 源管理；Web：通过 CP 与 VA 交互。

## 二、运行与部署
- Compose（GPU）：
  - 使用 `gpus: all` 注入 GPU（解决 `libcuda.so.1` 加载问题）。
  - 暴露 8082（REST）/9090（Prom）/50051（gRPC）；卷挂载 `/app/models`、`/logs`、（可选）`/app/.trt_native_cache`。
- 构建：
  - 基于 `nvidia/cuda:<ver>-cudnn-devel-ubuntu22.04`；容器内构建 ORT v1.23.x（启用 CUDA，按镜像条件启用 TRT EP）。
  - 统一 `CMAKE_CUDA_ARCHITECTURES="90;120"`；安装至 `/opt/onnxruntime` 并补全链接。

## 三、图与模型路径（多阶段）
- `docker/config/va/graphs/analyzer_multistage_example.yaml` 的 `det` 节点支持双路径：
  - `model_path_trt: models/<name>.engine`（原生 TensorRT 读取 .engine/.plan）
  - `model_path_ort: models/<name>.onnx`（ORT CUDA/ORT‑TRT 使用 ONNX）
- NodeModel 会根据 Engine.provider 自动选择路径（tensorrt‑native→优先 .engine；否则→优先 .onnx；均为空时回退 `model_path`）。

## 四、已落地的推理侧能力
- 原生 TensorRT（tensorrt‑native）：
  - 直接读取 `.engine/.plan` 反序列化为 `ICudaEngine`，创建 `IExecutionContext` 在统一 CUDA 流上推理。
  - 输出 dtype 自适应（FP16/FP32），避免将 FP16 误按 FP32 解析导致置信度被阈值过滤。
  - 显存管理：输入/输出设备缓冲在帧间按需回收，避免显存持续增长。
- ORT 路径：
  - 启用 CUDA/（镜像具备时）TRT EP；GPU 场景默认开启零拷贝链路（IoBinding 与统一计算流）。

## 五、异步预热（订阅时后台加载）
- 订阅创建后，后台异步执行 `open_all()` 预热模型/引擎，不阻塞订阅接口返回。
- 并发与耗时：
  - `engine.options.preopen_concurrency`（默认 2）限制并发预热数；
  - `engine.options.preopen_timeout_ms`（默认 10000）用于耗时阈值（日志告警）。
- 开启实时分析时（ON），若预热已完成则不再加载，直接推理。

## 六、NVENC 与编码
- NVENC 参数合规：仅当 `VA_NVENC_AQ_STRENGTH ∈ [1,15]` 时设置 `aq-strength`，避免 FFmpeg 报错；保持 `preset`/`rc` 等映射稳定。

## 七、日志与指标（当前可用）
- TensorRT：`analyzer.trt load: ... (engine) outputs=N`（可见加载成功与输出个数）。
- 推理/后处理：`ms.node_model`（输出个数与前几路形状，按节流打印）、`ms.nms boxes=…`。
- 控制：`analysis mode -> ON/OFF`、`/api/control/pipeline_mode` 返回状态码。
- 指标：Prom 基础指标（帧数、编码/传输相关）便于可用性观测。

## 八、控制流程
- 订阅：
  - `POST /api/subscriptions?stream_id=<id>&profile=det_720p&source_uri=<rtsp>` → 202（后台开始预热）。
- 切换模式：
  - `POST /api/control/pipeline_mode { stream_id, profile, analysis_enabled:true|false }`。
- （可选）热更新：
  - `POST /api/control/hotswap { pipeline_name, node, model_uri }` 更换模型。

## 九、风险与注意
- 驱动/工具链不匹配：`libcuda.so.1`/NVENC 打开失败 → 使用 `gpus: all` 与镜像自检；
- 预热与第一帧竞争：通过并发限制与一次性 open 降低二次加载；
- 模型/布局差异导致 boxes=0：先临时降低 `conf` 验证；
- 大文件推送：避免把 `.engine` 等二进制纳入 Git（使用 .gitignore/LFS）；
- 路径与权限：统一 `models/…` 相对路径；确保宿主卷权限与大小写一致。
