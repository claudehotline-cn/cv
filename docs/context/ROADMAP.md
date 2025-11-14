# 路线图总览

- **M0「训练与工件打通」**  
  - 目标：完成 Trainer 服务化与 CP 代理，使“训练 → MLflow 记录 → 本地/MinIO 工件产出（ONNX + manifest）”链路可用，并提供基础 `/training` 页面进行配置与监控。  
  - 验收：前端可发起训练并实时看到 SSE 事件与指标；本地/MinIO 中存在 `model.onnx/model.yaml`，MLflow 中有对应 Run 与工件记录。

- **M1「一键部署 + S3 + 推理画质基线」**  
  - 目标：打通 “Trainer → MinIO(S3) → CP → VA/Triton” 闭环，支持 accuracy/size_mb 门槛与一键部署；同时建立 VA H.264/NVENC 编码的默认画质基线（720p@30、8–10Mbps），确保前端 WHEP 播放画面清晰稳定。  
  - 验收：`POST /api/train/deploy` 在门槛满足时返回转换 Job 与 `/api/repo/convert/events`；转换完成后 `/api/repo/load` 能成功加载模型并在 VA 中推理；分析面板中 WHEP 流在推荐配置下主观画质达到“接近源级”。

- **M2「稳健运行与可观测」**  
  - 目标：完善健康检查、告警与指标体系，收敛训练/部署/画质相关配置；前端提供灰度与别名管理 UI，并能对画质调参（码率/分辨率/overlay）进行可视化观测与回滚。  
  - 验收：Grafana 面板展示训练/部署/推理/编码核心指标；定期回滚演练通过；MinIO 上模型与工件具备生命周期管理；画质调整有历史记录与一键回退能力。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | Trainer 服务 + CP 代理 + 基础 `/training` 页 | FastAPI + MLflow 集成；CP HTTP 反向代理；SSE 事件流；artifacts 目录规范 | 接口抖动、schema 变化频繁 → 约束 API 契约，配套文档与回归脚本 | 训练任务成功率 ≥ 95%；训练页表单提交错误率 ≤ 5% |
| M1 | 一键部署 + MinIO/S3 集成 + VA 编码基线 | Trainer S3 上传；MLflow S3 Artifact Store；CP 优先 `s3_uri`；VA In-Process + RepoConvertUpload；WHEP H.264/NVENC 路径打通 | MinIO 不可用或签名失败 → 设计 S3 失败回退 Trainer 下载；带宽不足导致画质劣化 → 给出推荐分辨率/码率档位与告警 | 满足门槛的部署放行率 ≥ 90%；转换失败率 ≤ 5%；720p@30 推流在推荐配置下主观画质达到预设评分 |
| M1.5 | 前端部署/分析面板 + 画质调参入口 | Pipelines 页面整合“一键部署/仅转换/灰度入口”；分析面板集成 WHEP Player 和画质状态提示；支持切换分析/原始与模型热切换 | 误操作风险 → 二次确认、只读模式与演练环境；WHEP 兼容问题 → 增加最小播放器调试页与统计面板 | 部署相关前端操作用户错误率 ≤ 5%；播放首帧延迟 ≤ 2s；切换分析模式黑屏时间 ≤ 1s |
| M2 | 可观测性与治理（含画质） | 训练/部署/推理/编码指标上报；对象存储版本化与清理策略；灰度与画质调参的自动化回滚剧本与演练 | 指标采集引入额外开销 → 采样与聚合控制；清理策略失误 → 仅清中间工件，保留主模型版本；画质调参扰动线上体验 → 先从 canary 流开始，失败自动回滚 | 指标采集开销 < 3% CPU；误删模型事件为 0；回滚演练成功率 100%；画质调参失败回滚时间 ≤ 5 分钟 |

---

# 依赖矩阵

- **内部依赖：**
  - `controlplane`：HTTP API 网关、训练/部署编排、灰度与别名管理、WHEP 反向代理。
  - `video-analyzer`：RTSP 解码（NVDEC/FFmpeg）、多阶段分析、H.264/NVENC 编码、WebRTC/WHEP 输出、Triton In-Process 推理与模型仓库。
  - `model-trainer`：训练循环、评估、MLflow 集成、工件生成与 S3 上传。
  - `web-front`：训练配置与监控、分析面板（WHEP 播放器 + 分析开关/热切换）、画质调参入口。

- **外部依赖（库/服务/硬件）：**
  - MySQL：`cv_cp` 库，训练作业与配置存储。
  - MLflow Tracking：Run、参数、指标与工件记录（S3 Artifact Store）。
  - MinIO：S3 兼容对象存储，用于 MLflow 工件与 Triton 模型仓库。
  - FFmpeg + NVENC：H.264/H.265 编码；本项目当前以 H.264 NVENC 为主。
  - gRPC/Protobuf：CP ↔ VA、CP ↔ VSM 通信。
  - PyTorch：Trainer 训练与推理框架。
  - TensorRT / `trtexec`：ONNX→TensorRT plan 转换工具链。
  - GPU：用于训练、推理与 NVENC，推荐但非强制；无 GPU 时需降级策略。

---

# 风险清单（Top-5）

- **训练/部署门槛误判** → 指标口径不一致或字段缺失  
  → 监控信号：MLflow 中 `accuracy/val/accuracy` 缺失率异常、deploy 门槛拒绝比例异常  
  → 预案：统一指标命名与落库逻辑；字段缺失时记录告警但允许可配置“软跳过”，避免阻塞所有部署。

- **MinIO/S3 不可用或访问异常** → 403/超时/签名错误  
  → 监控信号：S3 请求错误率、CP 日志中 S3 拉取失败与回退次数、部署时延显著升高  
  → 预案：S3 失败自动回退 Trainer HTTP 下载；为部署路径设置重试与熔断；提供离线同步/补传脚本，并在仪表板中明确标出当前部署数据来源（S3/HTTP）。

- **VA 未在线或转换/推理失败** → gRPC 连接失败、RepoConvertUpload 或推理路径错误率升高  
  → 监控信号：`/api/va/runtime` 探针失败、转换 Job 失败率提升、推理 QPS/FPS 突降  
  → 预案：部署前增加 VA 健康检查；失败时直接终止部署并返回可读错误；提供脚本重试转换与加载，并允许灰度/别名快速回滚。

- **WHEP 播放画质与兼容问题** → 浏览器端 H.264 解码表现差、噪点重、或 SDP/ICE 兼容问题  
  → 监控信号：前端 RUM 中 framesDropped/framesDecoded 比例异常、用户报障集中在特定浏览器版本、VA 日志中 WHEP 会话频繁重建  
  → 预案：给出推荐分辨率/码率与 NVENC 参数基线；提供最小 WHEP 播放调试页；通过环境变量与 profile 支持快速降级（降低分辨率、关闭 overlay 填充等）。

- **配置漂移与环境差异** → Compose 与生产配置不一致、编码参数被环境变量意外覆盖  
  → 监控信号：容器频繁重启、健康检查失败、`VA_NVENC_*` 环境变量与配置不一致、画质在不同环境差异巨大  
  → 预案：统一 `.env` 模板与配置说明；启动脚本中增加关键环境变量与 profile 一致性自检；在 CI 中对 Compose 与生产配置做静态校验，避免“暗改配置”。***
