# CONTEXT（2025-11-17，In-Process Triton + OCSORT 调试）

本文件汇总当前对话中围绕 “VideoAnalyzer In-Process Triton 集成、多阶段 OCSORT 图、per-node 推理配置与后续文档/路线规划” 的关键结论，作为后续开发与调试的统一上下文。

---

## 一、当前进度与关键决策

### 1. In-Process Triton 集成路径

- 已彻底删除 gRPC Triton client 路径：
  - 删除 `video-analyzer/src/analyzer/triton_session.{hpp,cpp}` 与所有 `USE_TRITON_CLIENT` 相关 CMake/Docker 逻辑。
  - VA 现在只通过 `libtritonserver.so` 的 In-Process C API（`TRITONSERVER_ServerNew/ServerLoadModel/ServerInferAsync` 等）调用 Triton。
- In-Process 会话实现：
  - 代码位置：`video-analyzer/src/analyzer/triton_inproc_session.cpp/.hpp`。
  - 主要特性：
    - 支持 GPU 输入与 GPU 输出，输出通过默认 ResponseAllocator + D2D 拷贝到会话级 GPU 缓冲。
    - 新增入口/输出调试日志（如 `[DebugSeg]`）方便配合 gdb 分析。
    - `loadModel()` 中使用 `TRITONSERVER_ServerModelMetadata + MessageSerializeToJson` 自动填充 `opt_.input_name`。
    - 针对 `input_name` 增加硬校验：若最终 `input_name` 仍为空，则视为 load 失败，记录 ERROR 日志并返回 `false`。
- gdb 崩溃分析（用户提供的 backtrace）：
  - 崩溃线程名 `grpcpp_sync_ser`，栈顶为 `triton::core::InferenceResponse::InferenceResponse(...)` → `TRITONBACKEND_ResponseNew` → `tensorrt::ModelInstanceState::Run`。
  - 说明 SIGSEGV 发生在 Triton/TensorRT backend 构造 `InferenceResponse` 时，我们自己的响应解析代码尚未执行。
  - 暂时结论：Triton 2.60.0 + TensorRT backend + In-Process + 某些输出配置组合存在内核级 bug，需要通过配置/降级绕开。

### 2. ModelSessionFactory 与 NodeModel 调整

- `video-analyzer/src/analyzer/model_session_factory.cpp`：
  - `provider='triton'` 分支只构造 `TritonInprocModelSession`，前提是 `engine.options` 中存在非空 `triton_outputs`。
  - 若未配置 `triton_outputs`，记录告警：
    - `"provider='triton' requested but no triton_outputs configured; falling back to cuda"`，
    - 并将 provider 回退为 `cuda`。
  - 从 `engine.options` 中解析以下字段填充 `TritonInprocModelSession::Options`：
    - `triton_model` / `triton_model_version`；
    - `triton_input` → `iopt.input_name`（存在时覆盖 metadata）；
    - `triton_outputs` → `iopt.output_names`（如 `"output0"` → `["output0"]`）；
    - `warmup_runs`、`triton_gpu_input/triton_gpu_output`；
    - `triton_repo`、`triton_backend_dir`；
    - `triton_pinned_mem_mb`、`triton_cuda_pool_device_id`、`triton_cuda_pool_bytes`；
    - `triton_backend_configs` 等高级 ServerOptions。
- `video-analyzer/src/analyzer/multistage/node_model.hpp/.cpp`：
  - 新增 per-node 字段，用于细粒度控制 Triton：
    - `model_path_triton_`：Triton 仓库模型名，例如 `"yolov12x"` / `"reid_passvitb"`。
    - `triton_input_override_`：按节点固定 Triton 输入名，例如 `"images"` 或 `"input"`。
    - `triton_outputs_override_`：按节点固定 Triton 输出名列表，例如 `"output0"` 或 `"feat"`。
  - `NodeModel::NodeModel` 从 Graph YAML 解析 `triton_input`/`triton_outputs` 字段。
  - `NodeModel::open` 中将 per-node 覆盖注入 `EngineDescriptor::options`：
    - 填充 `triton_model`、`triton_input`、`triton_outputs`，供 `ModelSessionFactory` 使用。
  - 保留 provider chain fallback（tensorrt-native → triton → tensorrt → cuda）与非 Triton provider 的输出名校验。

### 3. OCSORT 多阶段图（analyzer_multistage_ocsort）改造

- 图文件：`docker/config/va/graphs/analyzer_multistage_ocsort.yaml`。
- det 节点（YOLOv12x 检测）示例配置：
  - 目标：显式固定输入名/输出名，与 Triton config 中 `input: images` + `output: output0` 对齐，回到历史上稳定的组合。
  - 典型片段：
    ```yaml
    - name: det
      type: model
      params:
        in: "tensor:det_input"
        outs: "tensor:det_raw"
        triton_input: "images"
        triton_outputs: "output0"
        model_path_triton: "yolov12x"
        model_path_ort: "models/yolox.onnx"
        model_path: "models/yolox.onnx"
    ```
- reid 节点（Pass-ReID）示例配置：
  - 目标：为 ReID 也启用 In-Process Triton，避免出现 `unexpected inference input 'images' for model 'reid_passvitb'`。
  - 典型片段：
    ```yaml
    - name: reid
      type: model
      params:
        in: "tensor:roi_batch"
        outs: "tensor:reid"
        model_path_triton: "reid_passvitb"
        model_path_ort: "models/reid_passvitb.onnx"
        model_path: "models/reid_passvitb.onnx"
        triton_input: "input"
        triton_outputs: "feat"
    ```
- 同时对齐 ROI 流节点（如 `roi.batch.cuda`、`track.ocsort`）的 I/O key，修复 Graph finalize 报 `Graph input missing ...` 的问题。

### 4. Docker/CMake 与日志配置

- `video-analyzer/CMakeLists.txt`：
  - 移除所有 `USE_TRITON_CLIENT` 选项和相关链接，仅保留 `USE_TRITON_INPROCESS`。
- `docker/va/Dockerfile.gpu`：
  - 删除 tritonclient 构建阶段与 `/opt/tritonclient` 拷贝。
  - 构建时只传 `-DUSE_TRITON_INPROCESS=${VA_USE_TRT_INPROC:-OFF}`。
- `docker/compose/docker-compose.gpu.override.yml`：
  - 为 `va` 服务追加：
    - `TRITONSERVER_LOG_VERBOSE=1`；
    - `TRITONSERVER_LOG_INFO=1`；
  - 用于输出 Triton 详细日志辅助定位 In-Process 出错位置。

### 5. 日志与错误观测

- 用户日志中可见典型错误：
  - `ONNX Runtime failed to load model: Load model from models/yolov12x.onnx failed: File doesn't exist`
  - `ms.node_model: load failed provider='triton' path='models/yolov12x.onnx'`
  - `analyzer: provider='triton' requested but no triton_outputs configured; falling back to cuda`
- 说明：
  - 部分路径仍会尝试使用本地 `models/yolov12x.onnx`，而用户实际使用 MinIO S3 模型仓库；
  - 某些情况下 `provider='triton'` 但 `triton_outputs` 未配置，触发回退。

---

## 二、重要上下文、约束与用户偏好

### 1. 用户偏好与使用场景

- 语言：希望与 Agent 以中文交流。
- 前端行为：分析页默认只拉流、不启用推理；只有点“实时分析”后才期望后端开始推理。
  - 当前问题：在未点击实时分析时 VA 也会崩溃，说明某些后台 warmup 或 Graph 初始化路径仍在触发推理或模型加载。
- 推理路径偏好：
  - 优先使用 In-Process Triton + GPU I/O（尽量零拷贝），减少 gRPC 开销。
  - det/reid 模型优先走 In-Process；当 In-Process 不稳定时，可以接受回退到 ORT CUDA，但更希望通过配置稳定 In-Process。
- 模型仓库：
  - 优先使用 MinIO S3 模型仓库（例如 `s3://http://minio:9000/cv-models/models`）。
  - 本地 `models/*.onnx` 路径主要用于兼容/回退，不保证实际存在。

### 2. 环境与构建约束

- 本地 CLI 环境缺少 OpenCVConfig.cmake，直接在宿主上 `cmake -S video-analyzer -B build` 会失败；
  - 实际构建在 Docker GPU 镜像中完成（`docker/va/Dockerfile.gpu`）。
- gdb 调试在 `cv/va:latest-gpu` 容器内进行，二进制通常无完整调试符号；
  - 因此堆栈符号主要来自 `libtritonserver.so`、TensorRT backend 与标准库。

### 3. 关键设计约束与决策

- 不再使用 Triton gRPC client（`libgrpcclient`），所有 Triton 交互均为 In-Process。
- 对于 provider='triton' 的模型：
  - 要求必须显式配置 `triton_outputs`（engine 或 node 级），否则不启用 In-Process，回退到 `cuda` 等其他 provider。
- 对 `input_name` 采用“三层防御”策略：
  1. 从模型 metadata 自动填充；
  2. 允许 per-node 配置 `triton_input` 覆盖；
  3. 若最终仍为空，则视为 model load 失败，避免带空 input 进入推理。

---

## 三、尚未完成/待办事项

1. 处理 ONNX 本地路径缺失与 fallback 行为：
   - 现象：Triton In-Process 模型加载时仍有日志尝试访问 `models/yolov12x.onnx`，并报 “File doesn't exist”。
   - 需要检查：
     - `NodeModel::open` 中 provider chain 与 `dec.resolved`/`prov_resolved` 的组合逻辑；
     - `pick_path_for(prov_resolved)` 对 `"triton"`/`"triton-inproc"` 是否始终返回 `"__triton__"`；
     - 确保当最终 provider 是 Triton-InProcess 时，不再去尝试加载本地 ONNX。
   - 目标：Triton 路径只依赖 S3 仓库，不依赖本地 `models/*.onnx`。

2. 验证 det/reid In-Process 路径在实际前端使用场景中的稳定性：
   - 在 Docker GPU 环境中构建最新 VA 镜像后：
     - 打开分析页但不点实时分析，确认 VA 不再崩溃；
     - 点“实时分析”后确认：
       - det/reid 均使用 In-Process Triton（日志 provider=triton-inproc）；
       - 不再出现 `InferenceResponse` 构造阶段的 SIGSEGV。
   - 若崩溃消失，再观察性能与延迟是否符合预期。

3. 持续整理 `docs/context/CONTEXT.md` 与 `docs/context/ROADMAP.md`：
   - 本次已基于最新对话重写 CONTEXT，并将 ROADMAP 作为后续任务的一部分生成。
   - 后续若关键设计或路径发生变化，需要同步更新 CONTEXT 与 ROADMAP，以避免文档与实现偏离。

4. 梳理 In-Process 日志与防御策略：
   - 当前为了调试启用了较多 `[DebugSeg]` 日志和高 Verbose 的 Triton 日志。
   - 在确认稳定后，可以考虑：
     - 把 DebugSeg 日志纳入某个 log-level 开关；
     - 回收部分过于频繁的调试输出；
     - 设计更平滑的 fallback 策略（如 In-Process 失败时自动回退 ORT，并在日志中标明）。

---

## 四、关键数据与参考文件

- 代码文件：
  - `video-analyzer/src/analyzer/triton_inproc_session.cpp`：In-Process Triton 会话实现、input_name 校验、输出 D2D 拷贝逻辑。
  - `video-analyzer/src/analyzer/model_session_factory.cpp`：`provider='triton'` 分支、强制 `triton_outputs` 与 Options 映射。
  - `video-analyzer/src/analyzer/multistage/node_model.hpp/.cpp`：per-node `force_provider`、`model_path_triton`、`triton_input`/`triton_outputs` 配置与 provider chain。
  - `docker/config/va/graphs/analyzer_multistage_ocsort.yaml`：OCSORT 图中 det/reid 节点的 per-node Triton 配置（含固定输入/输出名）。
  - `docker/compose/docker-compose.gpu.override.yml`：VA GPU 环境配置（TRITONSERVER 日志、VA_USE_TRT_INPROC）。
  - `docker/va/Dockerfile.gpu`：VA GPU 镜像构建（仅 In-Process Triton）。
- 文档文件：
  - `docs/memo/2025-11-16.md`、`docs/memo/2025-11-17.md`：记录 gRPC client 删除、In-Process 集成、Graph/配置改动与 gdb 调试过程。
  - `docs/context/CONTEXT.md`：当前文件，作为后续 ROADMAP 与变更规划的基础。
  - 历史设计与计划文档（供深入参考）：
    - `docs/references/GPU_zero_copy_ocsort_multistage_plan.md`
    - `docs/plans/GPU_zero_copy_ocsort_multistage_tasks.md`

