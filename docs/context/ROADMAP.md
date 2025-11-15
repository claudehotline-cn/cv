# 路线图总览

- **M0「架构与文档基线」**  
  - 目标：固化整体架构视图与子系统详细设计，完成 `docs/design` 目录重构和 CONTEXT/ROADMAP 基线，确保文档结构准确反映当前实现。  
  - 验收：VA/CP/VSM/Web-Front/训练/存储/协议均有对应详细设计；`docs/design` 中无指向已删除文件的链接；所有 Mermaid 图在渲染环境下可正常解析。

- **M1「订阅管线与协议打通」**  
  - 目标：以 LRO 为核心完成 CP HTTP ↔ VA gRPC ↔ VSM 的订阅管线，实现统一的错误码与协议语义，并让前端 AnalysisPanel 稳定驱动订阅与播放。  
  - 验收：从 `POST /api/subscriptions` 到 `/whep` 的端到端链路在代表性场景下稳定；订阅 phase/timeline 在 UI 可视化；协议文档与实现保持一致，错误码覆盖主要失败场景。

- **M2「GPU 零拷贝与训练闭环」**  
  - 目标：在订阅稳定的基础上收敛 GPU 零拷贝路径行为，并打通 Trainer→MinIO/MLflow→CP→VA 的训练与部署闭环，配套可观测与前端控制。  
  - 验收：CPU/GPU 检测框差异在业务可接受范围内；zero-copy 路径可通过脚本和指标进行校准；训练任务可一键部署到 VA，并在前端完成验证与回滚。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | 更新的整体架构设计 + 子系统详细设计 + 文档目录重构 | 完成 `整体架构设计.md` 与 VA/CP/VSM/Web-Front 详细设计；重构 `docs/design` 子目录（architecture/subscription_pipeline/protocol/storage/observability/training）；在 CONTEXT/ROADMAP 中固化约定与术语 | 文档与代码偏离 → 抽样对照实现；在 `docs/memo` 记录每次重要设计变更，避免“只改代码不改设计” | 关键模块的架构/详细设计覆盖率 ≥ 90%；链接检查无 404；Mermaid 图解析通过 |
| M1 | LRO 订阅管线 + 协议与错误码设计 + 前端 AnalysisPanel 串联 | 实现并验证 `lro_subscription_design.md` 中的 Runner/Operation/Step；完成 `控制平面HTTP与gRPC接口说明.md` 与 `控制面错误码与语义.md`；让 AnalysisPanel 通过 `/api/subscriptions` + `/whep` 驱动订阅 | LRO 状态机复杂、协议收敛慢 → 先实现 happy path，并在附录保留历史方案；通过端到端测试与日志分析辅助收敛 | 订阅创建/查询/取消成功率 ≥ 99%；典型场景下首帧延迟与中断率满足产品要求；错误码覆盖主类失败 |
| M2 | GPU 零拷贝推理 + 训练与部署闭环 + 指标/面板 | 完成 `zero_copy_execution_详细设计.md`、`tensorrt_engine.md`、`triton_inprocess_integration.md` 实现与对齐；打通 Trainer→MinIO/MLflow→CP→VA 部署路径；在 Grafana 与前端增加相关指标与模式切换 | CUDA/IOBinding 行为差异导致降准；训练/部署链路依赖多服务 → 为关键 profile 提供 CPU NMS 回退；为训练与部署增加重试/熔断与旁路脚本 | 代表性样本下 CPU/GPU boxes 差异满足业务阈值；训练任务成功率 ≥ 95%；部署任务成功率 ≥ 90% |

---

# 依赖矩阵

- **内部依赖：**
  - `controlplane`：HTTP 网关、订阅 LRO 编排、训练与模型管理、WHEP 反向代理、错误码与协议聚合。
  - `video-analyzer`：RTSP 解码、多阶段 Graph、推理引擎（TensorRT/Triton In-Process）、GPU 零拷贝路径、WHEP 输出。
  - `video-source-manager`：RTSP 源管理与 Restream，`SourceControl` gRPC 状态/控制。
  - `model-trainer`：训练循环、评估、MLflow 集成与工件上传。
  - `web-front`：配置与控制界面、AnalysisPanel、订阅状态可视化与模式切换。

- **外部依赖（库/服务/硬件）：**
  - MySQL `cv_cp` 库、Redis 缓存；MinIO 与 MLflow Tracking 服务。
  - gRPC/Protobuf（CP↔VA、CP↔VSM）、FFmpeg/NVENC/NVDEC、TensorRT/Triton、PyTorch。
  - GPU 资源（推理与编解码），以及 Prometheus/Grafana 观测栈。

---

# 风险清单（Top-5）

- **订阅/LRO 状态机复杂度过高** → 触发条件：频繁新增 phase/原因码或跨文档定义不一致 → 监控信号：订阅失败率上升、日志中 reason_code 分布紊乱 → 预案：在 `lro_subscription_design.md` 和 `控制面错误码与语义.md` 中集中维护枚举，并通过 e2e 测试覆盖核心状态流转。  
- **GPU 零拷贝路径精度退化** → 触发条件：启用 CUDA 预处理/IOBinding/FP16/TRT 之后 → 监控信号：CPU/GPU boxes 差异和 miss_ratio 指标异常、Grafana 面板中相关 metrics 激增 → 预案：使用 compare/suggest 脚本对关键 profile 做基准校准，必要时回退到 CPU NMS 或关闭零拷贝。  
- **协议与实现漂移** → 触发条件：CP/VA/VSM 代码演进未同步更新 `protocol` 文档 → 监控信号：OpenAPI/Proto 生成结果与文档不一致、前端调用 4xx/5xx 比例上升 → 预案：为关键 HTTP/gRPC 接口建立契约测试，在 CI 中对照 `控制平面HTTP与gRPC接口说明.md` 做自动校验。  
- **设计文档与代码脱节** → 触发条件：重构或性能优化直接改代码，未更新 `architecture` 与专题设计 → 监控信号：CR/排障过程中频繁提到“文档不可信” → 预案：在 AGENTS 流程中强制“先改设计再改实现”，并通过 `docs/memo` 记录每次设计调整。  
- **基础设施不可用或容量瓶颈** → 触发条件：MySQL/MinIO/MLflow/Prometheus/Grafana 不稳定或容量不足 → 监控信号：连接错误率升高、时延抖动、磁盘使用率逼近阈值 → 预案：为关键服务配置高可用与报警阈值，提供降级路径（本地磁盘/缓存）、备份与扩容预案。  

