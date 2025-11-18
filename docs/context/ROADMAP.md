# 路线图总览

- **M0「In-Process Triton 稳定基线」**  
  - 目标：在保持现有接口行为不变的前提下，让 VA 使用 In-Process Triton 时稳定加载 MinIO 模型仓库，避免因 plan/配置不一致或消息尺寸限制导致崩溃或 5xx。  
  - 验收：常规图（含 det-only）在典型 RTSP 流上连续运行 ≥1 小时无崩溃；`RepoConvertUpload` 对 ≤1GB ONNX 能成功生成 plan 并被 Triton 加载；日志中无 `Received message larger than max`、plan 反序列化失败等错误。

- **M1「ReID 动态 Batch + OCSORT 目标追踪」**  
  - 目标：让 `analyzer_multistage_ocsort.yaml` 在 ReID 动态 batch（max_batch_size=128）的前提下端到端稳定运行，GPU 上完成 ROI 裁剪、ReID 特征提取和 OCSORT 轨迹更新，并保证追踪框绘制准确。  
  - 验收：在代表性流（含密集行人和遮挡场景）上连续运行 ≥30 分钟，追踪框位置与检测框一致、ID 稳定（ID 交换率可控）；ReID 调用批量大小随 ROI 数变化（log 中可观察 1~128 的 batch），显存和主机内存无持续增长。

- **M2「模型仓库 / 转换流水线与可观测性收敛」**  
  - 目标：打通从 trainer 导出 ONNX → CP/VA `convert_upload` → MinIO 模型仓库 → Triton In-Process 加载的流水线，并补齐日志与指标，形成可回溯的“模型来源 / 配置 / plan”视图。  
  - 验收：通过一条标准训练任务产出的 ReID/Det 模型，可以在 Web 模型页一键完成：上传 manifest+ONNX → `convert_upload` 生成 plan → `load` 并切换到新版本；MinIO 中 `config.pbtxt` 与 plan 一致，Prom/Grafana 能看到每个模型的加载状态、QPS、延迟与错误率。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | In-Process Triton 稳定基线（含 gRPC 限流） | 统一使用 In-Process Triton；在 `TritonInprocModelSession` 中显式配置 `input_name`/`output_names`；在 VA gRPC 服务器开启 1024MB 消息上限；为 DebugSeg 日志接入 `VA_LOG_THROTTLED` | plan 与运行时 TensorRT 版本不匹配 → 所有线上 plan 必须由 VA 容器内 trtexec 生成；MinIO 中旧 plan 清理掉，统一走 `RepoConvertUpload` | det-only 图在测试流上连续运行 ≥1h 无崩溃；`RepoConvertUpload` 对 ≤1GB ONNX 成功率 ≈100% |
| M1 | ReID 动态 batch + OCSORT 追踪闭环 | ReID config.pbtxt 正确声明 `max_batch_size=128` 与输入 dims；`RepoConvertUpload` 自动注入 `--min/opt/maxShapes`；多阶段图中 `reid` 节点直接消费 `[N,3,384,128]` 并输出 `[N,1536]` GPU 特征；`track.ocsort` GPU 路径正确使用 ReID 特征 | ReID plan 中 batch 维或特征维与 config/Graph 不一致 → 在构建和启动阶段增加自检脚本，比较 plan profile 与 config.pbtxt/Graph；必要时在 CP/VA 暴露“自检失败”状态 | 运行 OCSORT 图时，ReID 的 batch 形状在日志中可见（例如 1x/18x/32x…），且 ReID/Triton 无报错；追踪框位置准确、ID 抖动在肉眼可接受范围内 |
| M2 | 模型仓库 + 转换流水线 + 可观测性 | 在 CP/VA 端完善 `RepoGetConfig`/`RepoSaveConfig`/`RepoPutFile`/`RepoConvertUpload` 使用流程，统一面向 MinIO；为每个模型保留 manifest、config.pbtxt、plan 之间的链路标识（model/version/job-id）；在 Grafana 中增加模型维度的延迟/QPS/错误率面板 | 配置漂移（Graph ↔ config.pbtxt ↔ plan ↔ trainer manifest） → 在 `docs/context/CONTEXT.md` 和 `docs/memo` 中记录每次模型/Graph 变更；增加一个轻量级 CLI/脚本，对给定 model/version 做全链路体检 | 新模型从 trainer 导出到上线的全流程在 1 小时内可完成，且无人工手动拷贝 plan；任意时刻可追溯某个模型的来源 run-id / manifest / plan 生成任务 |

---

# 依赖矩阵

- **内部依赖：**
  - `video-analyzer`：
    - `TritonInprocModelSession` 与 `TritonInprocServerHost`（In-Process 调度与 GPU I/O 管理）。
    - `ModelSessionFactory` / `NodeModel`（provider 链与 per-node Triton 配置）。
    - 多阶段 Graph 节点：`roi.batch.cuda`、`track.ocsort`、`overlay.cuda`。
  - `controlplane`：
    - gRPC 客户端（`va_repo_convert_upload` 等）与 HTTP API（`/api/repo/add`、`/api/repo/convert_upload`、`/api/repo/load`）。
  - `web-front`：
    - 模型管理与转换页面（config.pbtxt 编辑、上传 ONNX、展示转换日志）。
  - 文档与备忘：
    - `docs/context/CONTEXT.md`、`docs/context/ROADMAP.md`、`docs/memo/YYYY-MM-DD.md`。

- **外部依赖（库/服务/硬件）：**
  - Triton Inference Server（含 TensorRT backend）。
  - TensorRT / CUDA 运行时与 GPU 驱动（版本需与 VA 镜像匹配）。
  - MinIO S3：模型仓库（`triton_repo = s3://...`）、正确配置 endpoint/AK/SK/region。
  - RTSP 摄像头或流媒体服务器：目标追踪场景的真实/测试视频源。

---

# 风险清单（Top-5）

- **1. plan 与运行时 TensorRT 版本不兼容**  
  - 描述：在 trainer 容器用不同版本 TensorRT 生成的 plan 被放入 MinIO，Triton 反序列化失败。  
  - 触发条件：线上环境 TensorRT 升级/降级或 trainer 镜像版本与 VA 镜像不一致。  
  - 监控信号：Triton 日志中出现 “unable to load plan file to auto complete config” 或 safeVersionRead 相关错误。  
  - 预案：规定所有线上 plan 必须由 VA 容器内 trtexec 通过 `RepoConvertUpload` 生成；对手动上传 plan 加门禁。

- **2. config.pbtxt 与 plan/Graph 配置漂移**  
  - 描述：`max_batch_size`、输入/输出名或 dims 与 plan/Graph 不一致，导致加载或推理阶段失败。  
  - 触发条件：手工编辑 config.pbtxt 或更换模型时未同步更新 Graph。  
  - 监控信号：Triton 报 “configuration specified max-batch N but TensorRT engine only supports 1”等错误；VA 日志出现 `unexpected inference input/output`。  
  - 预案：在 CP/VA 中增加自检（对比 plan profile 与 config/Graph）；在文档与 memo 中记录每次模型/Graph 变更。

- **3. 动态 batch 下显存/主机内存泄漏**  
  - 描述：ReID/OCSORT path 在长时间运行中未正确释放 ROI batch 或特征缓冲，导致内存持续增长。  
  - 触发条件：GPU buffer 未归还 GpuBufferPool，或 host 缓冲在循环中不断 append。  
  - 监控信号：nvidia-smi 与进程 RSS 呈单调上升，无平稳平台。  
  - 预案：已删除顺序 ReID 聚合路径，保留 ROI batch 和 OCSORT 状态的明确生命周期；继续通过长时间压测观察曲线，如仍有泄漏则用 `cuda-memcheck` 与自定义统计进一步定位。

- **4. ReID 特征与 ROI 对齐错误导致追踪框偏移或 ID 抖动**  
  - 描述：`tensor:reid` 中第 i 行特征与第 i 个 ROI 不对应，导致关联错误。  
  - 触发条件：ROI 排序在不同节点间被打乱、max_rois 截断策略不一致或 batch 维处理错误。  
  - 监控信号：在可视化结果中出现明显错绑（框跑偏、ID 频繁跳变）；日志中 ReID batch 大小与检测数不一致。  
  - 预案：强约束 `roi.batch.cuda` 与 ReID 输入的顺序（基于原始 NMS 输出顺序）；在调试时记录 `gdet.count` 与 ReID 输出 shape 的一致性；必要时增加断言。

- **5. MinIO 凭据/网络问题导致模型加载失败**  
  - 描述：MinIO endpoint 或 AK/SK 配置错误、网络不稳定造成 config/plan 读取失败。  
  - 触发条件：环境变量变更、MinIO 升级或网络抖动。  
  - 监控信号：VA 日志中出现 S3 curl 失败；Triton 报模型找不到；CP 模型页加载状态异常。  
  - 预案：在启动时对关键 bucket/prefix 做探活（HEAD/GET）；为 S3 操作增加重试与清晰的错误码；通过 Grafana 面板和告警监控 MinIO 相关错误率。

