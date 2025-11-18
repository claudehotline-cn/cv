# CONTEXT（2025-11-18，In-Process Triton + ReID 动态 Batch + OCSORT）

本文件汇总当前围绕 **VideoAnalyzer In-Process Triton 集成、MinIO 模型仓库、ReID 动态 Batch、OCSORT 目标追踪与内存/日志收敛** 的关键结论，作为后续开发与调试的统一上下文。

---

## 一、Triton In-Process 集成与日志收敛

- **仅保留 In-Process Triton 路径**
  - 已删除旧 gRPC Triton client（`triton_session.{hpp,cpp}` 与 `USE_TRITON_CLIENT` 相关逻辑），VA 只通过 `libtritonserver.so` C API 调用 Triton。
  - In-Process 会话实现位于：`video-analyzer/src/analyzer/triton_inproc_session.cpp/.hpp`。

- **TritonInprocModelSession 关键行为**
  - 支持 GPU 输入 / GPU 输出；输出通过 ResponseAllocator 优先落在 GPU device buffer，必要时 D2H 拷贝到 host。
  - `loadModel()` 不再依赖 ModelMetadata 动态发现输入名，要求通过 engine options 或 Graph per-node 显式配置 `triton_input`。
  - 若 `opt_.input_name` 为空，直接记录 ERROR 并拒绝加载（避免“神秘空输入名”）。

- **DebugSeg 日志节流**
  - 为排查 In-Process + TensorRT 的崩溃问题，在 `run()` 中加入了若干 `[DebugSeg]` 打点：
    - 入口：输入形状、on_gpu、use_gpu_input/use_gpu_output。
    - 请求准备：bytes、输出名数量。
    - 推理提交：ServerInferAsync 调用情况。
    - 响应解析：OutputCount 及每个输出的 name/bytes/memory type。
  - 这些日志现已统一改用 `logging_util` 的 `VA_LOG_THROTTLED(log_level_for_tag("inproc.triton"), log_throttle_ms_for_tag("inproc.triton"))`：
    - 默认不会每帧刷 Info，而是按标签和节流窗口输出；
    - 真正需要高频追踪时，可通过配置单独提升 `inproc.triton` 的日志级别与节流参数。

- **VA gRPC 服务器消息大小上限**
  - 在 `video-analyzer/src/controlplane/api/grpc_server.cpp` 中，所有 `ServerBuilder` 已调整为：
    - `SetMaxReceiveMessageSize(1024 * 1024 * 1024)`；
    - `SetMaxSendMessageSize(1024 * 1024 * 1024)`。
  - 目的：支持 ~328MB 的 ReID ONNX 以及转换后较大的 plan 在 `RepoConvertUpload` 等接口中流转，避免 `Received message larger than max (...)` 错误。

---

## 二、MinIO 模型仓库与 ONNX→TensorRT 自动转换

- **模型仓库结构（MinIO）**
  - 宿主机：`docker/model/`（不入 Git）挂载到容器内 `/models`。
  - 推荐结构（以 ReID 为例）：
    - `reid_passvitb/config.pbtxt`
    - `reid_passvitb/1/model.plan`
  - 真正的存储落在 MinIO（`triton_repo = s3://...`），VA/CP 通过 SigV4 + curl 读写。

- **RepoConvertUpload（VA 内部 trtexec 代理）**
  - 入口：`video-analyzer/src/controlplane/api/grpc_server.cpp::RepoConvertUpload`。
  - 流程：
    1. 从 CP 接收 `model`/`version` 与 ONNX bytes。
    2. 将 ONNX 写入 `/tmp/va_conv_onnxXXXXXX`，拼出 `plan_tmp = onnx_tmp + ".plan"`。
    3. 选取 `trtexec` 路径（req.trtexec / `TRTEXEC` 环境变量 / 默认候选列表）。
    4. 派生子进程 `execvp(trtexec, ...)` 调用 `trtexec` 生成 plan。
    5. 读回 `plan_tmp`，写入模型仓库：
       - 本地 FS：`<repo>/<model>/<version>/model.plan`；
       - S3/MinIO：`s3://.../<prefix>/<model>/<version>/model.plan`。

- **动态 batch 通用推断逻辑**
  - 新增 `TrtexecShapeHint` 与 `infer_shape_from_config(hopt, model)`：
    - 仅在 `triton_repo` 以 `s3://` 开头时工作；
    - 通过与 `RepoGetConfig` 一致的逻辑，从 MinIO 拉取 `<model>/config.pbtxt`：
      - 解析 `max_batch_size: N`；
      - 解析首个 `input` 的 `name` 与 `dims: [C,H,W,...]`（不含 batch 维）。
  - 若成功解析且 `max_batch_size > 1`：
    - 构造：
      - `--minShapes=<name>:1xC xH xW...`
      - `--optShapes=<name>:min(N,32)xC xH xW...`
      - `--maxShapes=<name>:N xC xH xW...`
    - 并同时追加到：
      - 用于日志的 `cmd` 字符串；
      - 子进程 `execvp` 的 `argv`。
  - 若解析失败或 `max_batch_size <= 1`：
    - 退回为旧行为：`trtexec --onnx=... --saveEngine=... --fp16`，由 TensorRT 默认给出 batch=1 的 profile。

- **ReID 模型 config.pbtxt 推荐配置**
  - ReID 模型 `reid_passvitb` 建议配置为：

    ```protobuf
    name: "reid_passvitb"
    platform: "tensorrt_plan"
    max_batch_size: 128

    input {
      name: "input"
      data_type: TYPE_FP32
      dims: [3, 384, 128]
    }

    output {
      name: "feat"
      data_type: TYPE_FP32
      dims: [1536]
    }

    instance_group {
      kind: KIND_GPU
      gpus: [0]
    }

    dynamic_batching {
      preferred_batch_size: [4, 8, 16, 32, 64, 128]
      max_queue_delay_microseconds: 2000
    }
    ```

  - 在此配置下，`RepoConvertUpload` 会自动生成支持 `N ∈ [1,128]` 的显式动态 batch plan，避免出现 “max-batch 128 but engine only supports 1” 的错误。

---

## 三、多阶段 OCSORT 图与 ReID 动态 Batch

- **Graph：`docker/config/va/graphs/analyzer_multistage_ocsort.yaml`**
  - 关键节点：
    - `pre`：`preproc.letterbox`，输出 `tensor:det_input`（1×3×640×640）。
    - `det`：YOLOv12x 检测（Triton）：
      - `in: "tensor:det_input"`，`outs: "tensor:det_raw"`；
      - `triton_input: "images"`，`triton_outputs: "output0"`；
      - `model_path_triton: "yolov12x"`（匹配 Triton 仓库模型名）。
    - `nms`：YOLO NMS，输出 ROI 列表 `rois["det"]`。
    - `roi`：`roi.batch.cuda`：
      - `in_rois: "det"`，`out: "tensor:roi_batch"`；
      - `out_w: 128`，`out_h: 384`，`max_rois: 128`；
      - 从 NV12 帧中裁剪并 letterbox 到 `[N,3,384,128]` 的 GPU tensor。
    - **`reid`：ReID 模型（Triton 动态 batch）**

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
          triton_gpu_output: "1"
      ```

      - 不再使用 `roi_seq_batch`；ReID 一次性处理 `[N,3,384,128]`，输出 `[N,1536]` GPU 特征。
    - `track`：`track.ocsort`：
      - 消费 `rois["det"]` + GPU 特征 `tensor:reid`（或 CPU 特征），更新轨迹状态；
      - GPU 路径下直接在设备端维护轨迹 boxes/ids/feats。
    - `ovl`：`overlay.cuda`：
      - `rois: "track"`，通过 track_id 绘制带 ID 的跟踪框。

- **NodeModel 行为调整（model 节点通用）**
  - `video-analyzer/src/analyzer/multistage/node_model.cpp/.hpp`：
    - per-node 传入的 `model_path_triton`、`triton_input`、`triton_outputs`、`triton_gpu_output` 会注入到 `EngineDescriptor::options` 中，供 `ModelSessionFactory` 构造 `TritonInprocModelSession` 使用。
    - 若 `in_key_ == "tensor:roi_batch"` 且本帧缺少该 tensor，则直接视为“空 ROI 集合”，返回 true，不再报错。这样无检测框时 ReID 节点不会中断流水线。
    - 旧的顺序 ReID 聚合路径（`roi_seq_batch_` + CPU/GPU 聚合缓冲）已完全移除：
      - 不再拆分 batch 逐 ROI 调用 `session_->run(single)`；
      - 只保留单次 `session_->run(batch)`，完全依赖 Triton plan 的动态 batch 能力。

---

## 四、内存/日志问题与当前状态

- **内存管理**
  - `NodeRoiBatchCuda` 在每帧处理前释放上一帧 `staged_` 中的 GPU buffer（通过 `GpuBufferPool::release`），避免 ROI batch 引起的显存堆积。
  - 顺序 ReID 聚合相关的 CPU/GPU 缓冲及 `cudaMemcpyAsync` 路径已删除，消除一类潜在的显存泄漏来源。
  - OCSORT GPU 状态由 `ocsort_alloc_state/ocsort_free_state` 管理，`max_tracks` 与 `feat_dim` 固定，主要内存来自持久化状态而非每帧临时分配。

- **日志收敛**
  - In-Process Triton DebugSeg 日志已节流；默认不再每帧输出 `TritonInproc::run enter`、`InferenceRequest prepared`、`ServerInferAsync dispatched`、`OutputCount`、`ResponseOutput[...]`。
  - 若需要重新打开详细追踪，可通过调整 `inproc.triton` 标签的日志级别与节流间隔实现。

---

## 五、后续重点验证与风险提示

1. **Plan 与 Triton 版本匹配**
   - 必须确保存储在 MinIO 的 `reid_passvitb/1/model.plan` 由 **VA 容器** 内的 TensorRT `trtexec` 生成，确保反序列化兼容；
   - 避免使用 trainer 容器中生成的 plan 直接覆盖线上版本。

2. **MinIO 上 config.pbtxt 与 plan 一致性**
   - `config.pbtxt` 中的 `max_batch_size` 与输入/输出 dims 必须与实际 plan 一致，否则 Triton 在 autofill 时会拒绝加载；
   - 建议统一通过前端模型页 + CP 的 `/api/repo/add` 与 `/api/repo/convert_upload` 管理 config 与 plan。

3. **ReID + OCSORT 行为**
   - 需要在 ReID 动态 batch 路径下验证：
     - ReID 特征 `tensor:reid` 的 `[N,D]` 与检测 ROI 顺序完全一致；
     - GPU OCSORT 使用的特征维度与 ReID 输出维度一致（当前为 1536）；
     - 追踪框绘制位置与检测框一致、ID 抖动可接受。

4. **异常 fallback 与调试路径**
   - 当 In-Process Triton 或某个模型加载失败时，应有清晰的 fallback 选项（如切回 ORT/CUDA）；
   - 所有关键决策与参数（provider 链、triton_repo、模型名、动态 batch 配置）需在 `docs/context/CONTEXT.md` 与 `docs/memo` 中保持同步，便于长期维护与回溯。

