# 项目上下文（2025‑11‑08｜VA/CP/VSM/Web + Docker + Triton）

本文汇总当前实现、关键决策与运行要点；面向排障、扩展与后续迭代。

## 一、架构与数据流
- VA：RTSP 拉流 → 预处理（NVDEC→CUDA Letterbox） → 推理（ORT CUDA/ORT‑TRT/原生 TensorRT） → 后处理（YOLO NMS：GPU/CPU） → 叠加（CUDA） → 编码（NVENC） → WHEP。
- CP：对外 REST（/api/subscriptions、/api/control/pipeline_mode、/api/control/hotswap），代理 WHEP；VSM：RTSP 源管理；Web：通过 CP 与 VA 交互。

## 二、运行与部署
- Compose（GPU）：`triton` 服务（HTTP:8000/gRPC:8001；`docker/model → /models`），`va/cp/vsm/web` 同网段；`gpus: all`；暴露 8082/9090/50051。
- 构建：Dockerfile.gpu 注入 SDK `/workspace/install`；`-DUSE_TRITON_CLIENT=ON`；OpenSSL 链接顺序修复；构建后 `ldd` 校验 `libgrpcclient.so`；yaml-cpp/gRPC/Protobuf 链接策略已兼容 Ubuntu。

## 三、图与模型路径（多阶段）
- `docker/config/va/graphs/analyzer_multistage_example.yaml` 的 `det` 节点支持双路径：
  - `model_path_trt: models/<name>.engine`（原生 TensorRT 读取 .engine/.plan）
  - `model_path_ort: models/<name>.onnx`（ORT CUDA/ORT‑TRT 使用 ONNX）
- NodeModel 会根据 Engine.provider 自动选择路径（tensorrt‑native→优先 .engine；否则→优先 .onnx；均为空时回退 `model_path`）。

## 四、已落地的推理侧能力
- 原生 TensorRT（tensorrt‑native）：反序列化 `.engine/.plan`，输出 dtype 自适应，设备缓冲按需回收。
- ORT：CUDA/（具备时）TRT EP；GPU 场景可用 IoBinding 零拷贝链路。
- Triton（T0/T1）：
  - gRPC 客户端已接入；`ModelSessionFactory` 映射 `triton|triton-grpc`。
  - 元数据自适配：可用时自动填充 I/O 名；遇到 batch-size 报错自动从“去 batch”切换为“保留 batch”并重试一次。
  - CUDA SHM（初版）：
    - 输入侧：稳定设备缓冲（cudaMalloc）+ IPC 注册，一次注册、帧间 D2D + 绑定；失败自动回退与熔断。
    - 输出侧：为每个输出分配稳定设备缓冲并注册 SHM，Infer 后优先返回设备侧 `TensorView`，不足则回退 Host。

## 五、异步预热（订阅时后台加载）
- 订阅创建后，后台异步执行 `open_all()` 预热模型/引擎，不阻塞订阅接口返回。
- 并发与耗时：
  - `engine.options.preopen_concurrency`（默认 2）限制并发预热数；
  - `engine.options.preopen_timeout_ms`（默认 10000）用于耗时阈值（日志告警）。
- 开启实时分析时（ON），若预热已完成则不再加载，直接推理。

## 六、NVENC 与编码
- NVENC 参数合规：仅当 `VA_NVENC_AQ_STRENGTH ∈ [1,15]` 时设置 `aq-strength`，避免 FFmpeg 报错；保持 `preset`/`rc` 等映射稳定。

## 七、日志与指标（当前可用）
- 直方图：`va_triton_rpc_seconds`、`va_model_session_load_seconds`、`va_graph_open_duration_seconds`。
- 失败计数：`va_triton_rpc_failed_total{reason=…}`（create/invalid_input/mk_input/mk_output/infer/no_output/timeout/unavailable/other 及 shm_ipc/shm_register/shm_bind）。
- 日志节流：`analyzer.triton` 的 `run in_shape=…` 默认 1000ms；`ms.node_model/ms.nms/ms.overlay` 支持模块节流与级别覆盖（env）。

## 八、控制流程
- 订阅：
  - `POST /api/subscriptions?stream_id=<id>&profile=det_720p&source_uri=<rtsp>` → 202（后台开始预热）。
- 切换模式：
  - `POST /api/control/pipeline_mode { stream_id, profile, analysis_enabled:true|false }`。
- （可选）热更新：
  - `POST /api/control/hotswap { pipeline_name, node, model_uri }` 更换模型。

## 九、风险与注意
- 驱动/工具链不匹配：`libcuda.so.1`/NVENC 打开失败 → `gpus: all` 与镜像自检。
- SHM 注册失败：命名冲突/残留或 IPC 不可用；已唯一化命名并在注册前反注册，仍失败自动回退与熔断。
- 批/动态形状差异：已提供自适应重试与 `triton_no_batch`；建议通过 Metadata/Config 校验。
- 模型布局导致 `boxes=0`：临时降低 `conf` 验证，必要时调整后处理布局。
- 大文件与权限：避免提交 `.engine`；统一 `models/…` 路径与权限大小写。
