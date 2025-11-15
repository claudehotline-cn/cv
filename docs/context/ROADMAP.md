# 路线图总览

- **M0「架构与文档基线」**  
  - 目标：固化整体架构视图与子系统/专题详细设计，完成 `docs/design` 重构与 CONTEXT/ROADMAP 更新，使文档结构与当前实现一一对应。  
  - 验收：VA/CP/VSM/Web-Front/训练/存储/协议/观测均有对应详细设计；`docs/design` 中无指向已删除文件的链接；Mermaid 图在常用渲染环境下可正常解析。

- **M1「订阅流水线与协议打通」**  
  - 目标：以 LRO 为核心完善订阅流水线，使 Web-Front→CP HTTP→VA LRO→Graph→推理引擎→WHEP 全链路稳定，协议与错误码语义收敛到统一文档。  
  - 验收：典型场景下从 `POST /api/subscriptions` 到 `/whep` 播放的端到端成功率达预期；订阅 phase/timeline 在前端可视化；`lro_subscription_design.md` 与 `subscription_pipeline_详细设计.md`、协议文档与实现保持一致。

- **M2「GPU 零拷贝与训练闭环」**  
  - 目标：在订阅稳定基础上收敛 GPU 零拷贝路径行为，并打通 Trainer→MinIO/MLflow→CP→VA 的训练与部署闭环，配套指标面板与前端控制。  
  - 验收：CPU/GPU 检测框差异在业务可接受范围内；zero-copy 路径可通过脚本/指标校准；训练任务可一键部署到 VA 并在前端完成验证/回滚。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | 更新的整体架构设计 + 子系统/专题详细设计 + 文档目录重构 | 完成 `整体架构设计.md` 及 VA/CP/VSM/Web-Front 详细设计；完善 `subscription_pipeline_详细设计.md`、`storage_详细设计.md`、`observability_详细设计.md` 等专题；收敛 `docs/design` 子目录结构并删除冗余文件 | 文档与代码偏离 → 抽样对照实现；在 `docs/memo` 记录每次设计调整；定期扫描死链与无效引用 | 架构/详细设计覆盖主要模块（≈90%）；文档链接检查无 404；新文档结构获得团队认可 |
| M1 | LRO 订阅流水线 + 协议与错误码设计 + 前端 AnalysisPanel 串联 | 落实 `lro_subscription_design.md` 与 `subscription_pipeline_详细设计.md` 中的 Runner/Step/职责边界；完善 `控制平面HTTP与gRPC接口说明.md`、`控制面错误码与语义.md`；让 AnalysisPanel 通过 `/api/subscriptions` + `/whep` 稳定驱动订阅 | LRO 状态机复杂、协议收敛慢 → 优先实现 happy path，在附录保留历史方案；用 e2e 测试和日志/指标辅助收敛 | 订阅创建/查询/取消成功率 ≥ 99%；首帧延迟与中断率满足产品目标；关键错误场景均有明确 reason_code |
| M2 | GPU 零拷贝推理 + 训练与部署闭环 + 指标/面板 | 按 `zero_copy_execution_详细设计.md`、`tensorrt_engine.md`、`triton_inprocess_integration.md` 收敛 GPU 路径；打通 Trainer→MinIO/MLflow→CP→VA 部署链路；在 Grafana 与前端增加相关指标与模式切换 | CUDA/IOBinding 行为差异导致降准；训练/部署链路依赖多服务 → 为关键 profile 提供 CPU NMS 回退；为训练与部署增加重试/熔断与旁路脚本 | 代表性样本下 CPU/GPU boxes 差异满足业务阈值；训练任务成功率 ≥ 95%；部署任务成功率 ≥ 90% |

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

- **订阅/LRO 状态机复杂度过高** → 触发条件：频繁新增 phase/原因码或跨文档定义不一致 → 监控信号：订阅失败率上升、日志中 reason_code 分布紊乱 → 预案：在 `lro_subscription_design.md` 与 `控制面错误码与语义.md` 中集中维护枚举，并通过 e2e 测试覆盖核心状态流转。  
- **GPU 零拷贝路径精度退化** → 触发条件：启用 CUDA 预处理/IOBinding/FP16/TRT 后 → 监控信号：CPU/GPU boxes 差异和 miss_ratio 异常、Grafana 中相关 metrics 激增 → 预案：使用 compare/suggest 脚本对关键 profile 做基准校准，必要时回退到 CPU NMS 或关闭零拷贝。  
- **协议与实现漂移** → 触发条件：CP/VA/VSM 演进未同步更新 `protocol` 文档 → 监控信号：OpenAPI/Proto 结果与文档不一致、前端 4xx/5xx 比例上升 → 预案：为关键 HTTP/gRPC 接口建立契约测试，在 CI 中对照 `控制平面HTTP与gRPC接口说明.md` 自动校验。  
- **设计文档与代码脱节** → 触发条件：重构或性能优化只改代码不改设计 → 监控信号：CR/排障中频繁出现“文档不可信”反馈 → 预案：在 AGENTS 流程中强制“先改设计再改实现”，并通过 `docs/memo` 记录每次设计调整。  
- **基础设施不可用或容量瓶颈** → 触发条件：MySQL/MinIO/MLflow/Prometheus/Grafana 不稳定或容量不足 → 监控信号：连接错误率上升、时延抖动、磁盘使用率逼近阈值 → 预案：为关键服务配置高可用与报警阈值，提供降级路径（本地磁盘/缓存）、备份与扩容预案。  

