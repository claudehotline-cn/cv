# 路线图总览

- **M0「训练与工件打通」**  
  - 目标：完成 Trainer 服务化与 CP 代理，使“训练 → MLflow 记录 → MinIO 工件（ONNX + manifest）」链路可用，并提供基础 `/training` 页面进行配置与监控。  
  - 验收：前端可发起训练并实时看到 SSE 事件与指标；MinIO 中存在 `model.onnx/model.yaml`，MLflow 中有对应 Run 与工件记录。

- **M1「一键部署 + Triton 推理 + 编码/画质基线」**  
  - 目标：打通 “Trainer → MinIO(S3) → CP → VA/Triton” 闭环，支持 accuracy/size_mb 门槛与一键部署；同时建立 VA H.264/NVENC 编码和 WHEP 播放的默认画质基线（720p@30、8–10Mbps），确保前端画面清晰稳定。  
  - 验收：`POST /api/train/deploy` 在门槛满足时返回转换 Job；转换完成后 `/api/repo/load` 能成功加载模型并在 VA 中推理；分析面板在推荐配置下主观画质达到“接近源级”。

- **M2「GPU 零拷贝 + IOBinding 稳定性与可观测」**  
  - 目标：在部署闭环稳定的基础上，收敛 VA GPU 零拷贝（NVDEC→CUDA 预处理→IOBinding→Triton）路径的行为，使 CPU 与 GPU 检测框在业务上可接受的一致性范围内；前端分析页提供 CPU/GPU 模式切换以及基于日志/指标的可观测面板。  
  - 验收：在典型场景下 CPU/GPU boxes median 差异 ≤ 10%；GPU 路径 miss_ratio（CPU>0,GPU=0）低于预设阈值；Grafana 能展示 decode/NMS 相关指标；前端可一键切换“精度优先（CPU NMS）/性能优先（GPU 零拷贝）”并看到指标变化。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | Trainer 服务 + CP 代理 + `/training` 页 | FastAPI + MLflow + MinIO 集成；CP 代理 Trainer；SSE 日志与指标流；工件目录规范 | 接口/Schema 变化频繁 → 固定版本化 API，配回归脚本与示例配置 | 训练任务成功率 ≥ 95%；训练页表单提交错误率 ≤ 5% |
| M1 | 一键部署 + Triton/TensorRT plan 管理 + VA 编码基线 | Trainer S3 上传；MLflow S3 Artifact Store；CP 选择 plan；VA In-Process/Triton 加载 plan；WHEP H.264/NVENC 打通 | MinIO 不可用或签名失败 → 回退 Trainer HTTP 下载；带宽不足导致画质劣化 → 给出推荐分辨率/码率档位与告警 | 满足门槛的部署放行率 ≥ 90%；转换失败率 ≤ 5%；720p@30 推流在推荐配置下主观评分达预设标准 |
| M1.5 | 前端部署/分析面板 + 画质/模式调参入口 | Pipelines 页面整合“一键部署/灰度入口”；分析面板集成 WhepPlayer 和画质状态提示；支持切换分析/原始与模型热切换 | 误操作风险 → 二次确认、演练环境；WHEP 兼容问题 → 提供最小播放器调试页与 stats 面板 | 部署相关前端操作用户错误率 ≤ 5%；首帧延迟 ≤ 2s；切换分析模式黑屏时间 ≤ 1s |
| M2 | GPU 零拷贝 + IOBinding 行为收敛 + 可观测 | NVDEC→CUDA 预处理→IOBinding→Triton 全链路 FP32 校准；YOLO decode/NMS CPU/GPU 规则对齐；提供 compare/suggest 脚本与 Grafana 面板；前端增加 CPU/GPU 模式 Switch | CUDA 精度/算子差异导致“小目标降准” → 先在 FP32 + CPU NMS 下建立基线，再启用 FP16/TRT；统一 decode/NMS 规则并使用脚本对 GPU 的 conf/iou 做重标定 | 在代表性样本上 CPU/GPU boxes median 差异 ≤ 10%；GPU miss_ratio ≤ 0.2；NMS 内核 deterministic；问题定位时间 ≤ 30 分钟 |

---

# 依赖矩阵

- **内部依赖：**
  - `controlplane`：HTTP API 网关、训练/部署编排、灰度与别名管理、WHEP 反向代理、LRO `subscriptions`。
  - `video-analyzer`：RTSP 解码（NVDEC）、多阶段分析、H.264/NVENC 编码、WHEP 输出、Triton In-Process 推理、IOBinding + GPU 零拷贝。
  - `model-trainer`：训练循环、评估、MLflow 集成、工件生成与 S3 上传。
  - `web-front`：训练配置与监控、分析面板（WhepPlayer + 分析开关/模式切换）、后续 CPU/GPU 模式 Switch。

- **外部依赖（库/服务/硬件）：**
  - MySQL：`cv_cp` 库，训练作业、源、pipeline 与 graph 存储。
  - MLflow Tracking：Run、参数、指标与工件记录（S3 Artifact Store）。
  - MinIO：S3 兼容对象存储，用于 MLflow 工件与 Triton 模型仓库。
  - FFmpeg + NVENC/NVDEC：H.264/H.265 编码与解码；当前以 H.264 NVENC + NVDEC 为主。
  - gRPC/Protobuf：CP ↔ VA、CP ↔ VSM 通信。
  - PyTorch：Trainer 训练与推理框架。
  - TensorRT / `trtexec`：ONNX→TensorRT plan 转换工具链。
  - GPU：用于训练、推理与 NVENC/NVDEC；无 GPU 时需降级路径（CPU decode + CPU NMS）。

---

# 风险清单（Top-5）

- **训练/部署门槛误判** → 指标口径不一致或字段缺失  
  → 触发条件：新模型导出 schema 变化、Trainer/CP 未同步更新  
  → 监控信号：MLflow 中关键指标（如 `val/accuracy`）缺失率异常、deploy 拒绝比例异常  
  → 预案：统一指标命名与落库逻辑；字段缺失时记录告警但允许可配置“软跳过”，避免阻塞所有部署。

- **MinIO/S3 不可用或访问异常** → 403/超时/签名错误  
  → 触发条件：MinIO 宕机或网络异常  
  → 监控信号：S3 请求错误率、CP 日志中 S3 拉取失败与回退次数、部署时延显著升高  
  → 预案：S3 失败自动回退 Trainer HTTP 下载；为部署路径设置重试与熔断；提供离线同步/补传脚本，并在 Grafana 中明确标出当前部署数据来源（S3/HTTP）。

- **VA 未在线或推理失败** → gRPC 连接失败、Triton In-Process 报错  
  → 触发条件：VA 容器未启动/崩溃、模型 plan 不兼容  
  → 监控信号：VA 探针失败、转换 Job 失败率提升、推理 QPS/FPS 突降  
  → 预案：部署前增加 VA 健康检查；失败时直接终止部署并返回可读错误；提供脚本重试转换与加载，并允许快速灰度/别名回滚。

- **GPU 零拷贝路径降准（小目标漏检）** → CUDA 预处理/IOBinding/decode/NMS 行为与 CPU 不完全等价  
  → 触发条件：开启 `use_cuda_preproc` / `use_cuda_nms` / FP16 plan 后  
  → 监控信号：对比脚本中 CPU/GPU boxes 差异大、miss_ratio 升高；Grafana 中 GPU 路径 boxes 数突降  
  → 预案：先在 FP32 + CPU NMS 模式下建立基准；统一 decode/NMS 规则；使用 `suggest_gpu_nms_thresholds.py` 对 GPU 的 conf/iou 做重标定；必要时对关键 profile 回退 CPU NMS。

- **WHEP 播放画质与兼容问题** → 浏览器端 H.264 解码差、噪点重、或 SDP/ICE 兼容问题  
  → 触发条件：浏览器升级、编码/码率配置变更  
  → 监控信号：前端 RUM 中 framesDropped/framesDecoded 比例异常、用户报障集中在特定浏览器版本、VA 日志中 WHEP 会话频繁重建  
  → 预案：给出推荐分辨率/码率与 NVENC 参数基线；提供最小 WHEP 播放调试页；通过 profile 和环境变量支持快速降级（降低分辨率、关闭 overlay 填充等）。

- **配置漂移与环境差异** → Compose 与生产配置不一致、编码/引擎参数被环境变量意外覆盖  
  → 触发条件：手工改 compose/配置文件、不同环境加载不同 `app.yaml`/graph  
  → 监控信号：容器频繁重启、健康检查失败、`VA_NVENC_*` 与 graph NMS/conf 等配置不一致、CPU/GPU 行为在不同环境差异巨大  
  → 预案：统一 `.env` 模板与配置说明；在启动脚本中增加关键环境变量与 profile 一致性自检；在 CI 中对 Compose/graph 与生产配置做静态校验，避免“暗改配置”。***
