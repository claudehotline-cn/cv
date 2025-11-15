# 路线图总览

- **M0「架构与文档基线」**  
  - 目标：固化整体架构视图与子系统/专题设计，完成 CONTEXT/ROADMAP 与设计文档重构，使文档结构与代码实现一一对应。  
  - 验收：VA/CP/VSM/Web-Front/训练/存储/协议/观测均有完整详细设计；`docs/design` 无死链；Mermaid 图在常见渲染环境下可正常解析。

- **M1「订阅流水线与协议打通」**  
  - 目标：以 LRO 为核心完成订阅流水线，使 Web-Front→CP HTTP→VA LRO→Graph→推理引擎→WHEP 全链路稳定，错误码与协议语义收敛到统一文档。  
  - 验收：典型场景下从 `POST /api/subscriptions` 到 `/whep` 播放的端到端成功率达预期；订阅 phase/timeline 在前端可视化；`subscription_pipeline_详细设计.md` 与协议文档及实现保持一致。

- **M2「GPU 零拷贝与 OCSORT 追踪闭环」**  
  - 目标：在订阅链路稳定的基础上，完成以 OCSORT 为代表的多阶段追踪 Graph，打通「检测 + ReID + 追踪 + 叠加」全 GPU 零拷贝路径，并与 Trainer→MinIO/MLflow→CP→VA 的训练/部署闭环协同。  
  - 验收：代表性场景下 CPU/GPU 检测/追踪结果差异在可接受范围；OCSORT Graph 在多流场景下稳定运行；前端可选择追踪模式并查看轨迹/指标。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | 更新的整体架构设计 + 子系统/专题详细设计 + 文档目录重构 | 完成 `整体架构设计.md` 与 VA/CP/VSM/Web-Front 详细设计；完善 `subscription_pipeline_详细设计.md`、`storage_详细设计.md`、`observability_详细设计.md` 等专题；收敛 `docs/design` 结构并清理冗余文档 | 文档与代码偏离 → 定期抽样对照实现；在 `docs/memo` 记录每次设计调整；增加死链扫描脚本 | 架构/详细设计覆盖主要模块（≈90%）；文档链接检查无 404；文档结构获得团队认可 |
| M1 | LRO 订阅流水线 + 协议与错误码收敛 + AnalysisPanel 串联 | 落实 Runner/Step/状态机设计；完善 `控制平面HTTP与gRPC接口说明.md` 与 `控制面错误码与语义.md`；让 AnalysisPanel 通过 `/api/subscriptions` + `/whep` 驱动订阅 | LRO 状态机复杂、协议同步困难 → 优先实现 happy path，在附录保留历史方案；通过 e2e 测试和日志/指标收敛边界条件 | 订阅创建/查询/取消成功率 ≥ 99%；首帧延迟/中断率满足产品目标；关键错误场景均有明确 reason_code |
| M2 | GPU 零拷贝推理 + OCSORT 多阶段追踪 + 训练/部署闭环 | 依据 `zero_copy_execution_详细设计.md`、`tensorrt_engine.md`、`GPU_zero_copy_ocsort_multistage_plan.md` 收敛 GPU 路径；实现多阶段 Graph（pre→det→nms→roi→reid→track→ovl）在 GPU 上执行；打通 Trainer→MinIO/MLflow→CP→VA 部署链路；在 Grafana 与前端增加追踪相关指标与模式切换 | CUDA/IOBinding 行为差异导致降准；OCSORT GPU 内核复杂度高 → 先保留 CPU fallback，使用对拍脚本验证 CPU/GPU 轨迹一致性；为关键 profile 提供回退开关；训练/部署链路依赖多服务 → 为训练与部署增加重试/熔断与旁路脚本 | CPU/GPU boxes 与轨迹差异满足业务阈值；OCSORT Graph 在目标场景稳定运行；训练任务成功率 ≥ 95%；部署成功率 ≥ 90% |

---

# 依赖矩阵

- **内部依赖：**
  - `controlplane`：HTTP 网关、订阅 LRO 编排、训练与模型管理、WHEP 反向代理、错误码与协议聚合。
  - `video-analyzer`：RTSP 解码、多阶段 Graph、推理引擎（TensorRT/Triton In-Process）、GPU 零拷贝路径、OCSORT 多阶段追踪、WHEP 输出。
  - `video-source-manager`：RTSP 源管理与 Restream，`SourceControl` gRPC 控制。
  - `model-trainer`：训练循环、评估、MLflow 集成与模型导出（含 ReID/OCSORT 相关模型）。
  - `web-front`：配置与控制界面、AnalysisPanel、轨迹与订阅状态可视化与模式切换。

- **外部依赖（库/服务/硬件）：**
  - MySQL `cv_cp` 库、Redis 缓存；MinIO 与 MLflow Tracking 服务。
  - gRPC/Protobuf（CP↔VA、CP↔VSM）、FFmpeg/NVENC/NVDEC、TensorRT/Triton、PyTorch、ModelScope（用于 OCSORT 模型）；
  - GPU 资源（推理+编解码），以及 Prometheus/Grafana 观测栈。

---

# 风险清单（Top-5）

- **订阅/LRO 状态机复杂度过高** → 触发条件：频繁新增 phase/原因码或跨文档定义不一致 → 监控信号：订阅失败率上升、日志中 reason_code 分布紊乱 → 预案：在 `lro_subscription_design.md` 与 `控制面错误码与语义.md` 中集中维护枚举；通过 e2e 测试覆盖核心状态流转，并在 CI 中加入契约校验。  
- **GPU 零拷贝路径精度退化（检测/追踪）** → 触发条件：启用 CUDA 预处理/IOBinding/FP16/TRT/OCSORT GPU 内核后 → 监控信号：CPU/GPU boxes 与轨迹差异、miss_ratio 异常，Grafana 中相关 metrics 激增 → 预案：使用 compare 脚本对关键 profile 做基准校准，必要时回退到 CPU NMS/追踪或关闭零拷贝。  
- **OCSORT 多阶段 Graph 与 TrackManager 职责边界模糊** → 触发条件：Graph 内追踪逻辑与 TrackManager 行为重叠或不一致 → 监控信号：轨迹 ID 不稳定、重复或泄露；Graph/TrackManager 双处更新同一状态 → 预案：在设计文档中明确边界（Graph 负责单流视觉阶段，TrackManager 负责订阅级 orchestrator），通过接口约束和回归测试保证一致性。  
- **协议与实现漂移（特别是订阅/追踪相关）** → 触发条件：接口演进未同步更新 `protocol` 文档 → 监控信号：OpenAPI/Proto 与实现不一致、前端 4xx/5xx 比例上升 → 预案：为关键 HTTP/gRPC 接口建立契约测试，在 CI 中对照 `控制平面HTTP与gRPC接口说明.md` 自动校验；对 OCSORT Graph 增加端到端回归。  
- **基础设施或 GPU 资源瓶颈** → 触发条件：MySQL/MinIO/MLflow/Prometheus/Grafana 或 GPU 资源不足/不稳定 → 监控信号：连接错误率上升、时延抖动、GPU 利用率/显存使用率异常 → 预案：为关键服务配置高可用和告警阈值，提供降级路径（本地磁盘/缓存、CPU 模式 Graph），以及清晰的扩容与回滚方案。  
