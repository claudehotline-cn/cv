# 路线图总览

- **M0「In-Process Triton 稳定基线」**  
  - 目标：在不修改前端行为的前提下，让 VA 使用 In-Process Triton 时在「分析页打开但未点实时分析」场景不再崩溃，det/reid 节点通过 per-node 固定输入/输出名稳定运行。  
  - 验收：打开分析页但不启用实时分析时 VA 无崩溃；仅在前端开启实时分析后才出现推理负载；日志中不再出现 `InferenceResponse` 相关 SIGSEGV 和本地 ONNX `File doesn't exist` 报错。

- **M1「OCSORT 多阶段图 + MinIO 仓库打通」**  
  - 目标：让 `analyzer_multistage_ocsort.yaml` 在 MinIO S3 模型仓库 + Triton In-Process 环境下端到端稳定运行（检测 + ReID + 追踪 + 叠加），并保证 provider/fallback 链路行为可预期。  
  - 验收：使用 OCSORT 图在代表性 RTSP 测试源上连续运行，帧处理数 > 0 且无 HTTP/RTSP 错误；det/reid 节点实际 provider 为 `triton-inproc`，仅在显式配置时才回退到其他 provider。

- **M2「性能与可观测性收敛」**  
  - 目标：在 M0/M1 稳定基础上，收敛 Triton/VA 日志级别、完善告警与指标，明确 In-Process fallback 策略，并评估 GPU 资源占用与延迟表现。  
  - 验收：关闭调试开关后日志噪音显著下降；关键指标（端到端延迟、GPU/CPU 利用、显存占用）满足目标阈值；在 In-Process 出现异常时能平滑回退到 ORT/CUDA，且有清晰告警与报错信息。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| M0 | 稳定的 In-Process Triton 基线（det/reid per-node 输入/输出固定） | 完成 `TritonInprocModelSession` Options 映射；`NodeModel` 支持 `triton_input`/`triton_outputs` per-node 配置；修正 `pick_path_for` 等逻辑，确保 provider='triton' 时只走 In-Process，不再尝试本地 ONNX | Triton 内部 bug 或响应构造异常 → 通过固定输出名、限制输出集合绕开；必要时提供 provider 回退（cuda/ort），并加 gdb/日志锚点 | 打开分析页不点实时分析 VA 不崩溃；det/reid 配置正确时推理成功率 ≈ 100% |
| M1 | OCSORT 多阶段图在 MinIO + Triton 环境下的稳定运行 | 在 `analyzer_multistage_ocsort.yaml` 中为 det/reid 明确 `model_path_triton` 与 `triton_input`/`triton_outputs`；验证 Graph I/O key 链路（包括 `roi.batch.cuda`、`track.ocsort` 等）；确保模型实际从 MinIO/Triton 加载 | 模型路径与仓库配置不一致 → 在日志中打印实际加载的 model repo/model name；提供脚本快速检查 S3 与 Graph 配置是否匹配 | OCSORT 图在标准测试源上持续运行 30 分钟无崩溃；日志中无本地 ONNX `File doesn't exist` 报错 |
| M2 | 性能/可观测性与防御策略收敛 | 降低 `[DebugSeg]` 等调试日志级别；在 docker-compose 中为 Triton/VA 配置合理日志等级与环境变量；增加关键指标（推理 QPS/端到端延迟/失败率）；明确 In-Process 异常时的 fallback 策略与开关 | 观测不足或 fallback 行为不可预期 → 在 `docs/context/CONTEXT.md` 与设计文档中记录决策；增加 smoke test 覆盖典型异常分支；为重要开关提供配置项 | 在目标场景下 GPU 利用率与延迟稳定；告警与日志能快速定位 In-Process or provider 问题；fallback 触发率在预期范围内 |

---

# 依赖矩阵

- **内部依赖：**
  - `video-analyzer`：`TritonInprocModelSession`、`ModelSessionFactory`、`NodeModel`、`analyzer_multistage_ocsort.yaml`、多阶段 Graph 与 Pipeline 运行时。
  - `controlplane`：AnalysisPanel 对应的 API（分析页打开/关闭、实时分析开关），确保前端行为与后端推理生命周期一致。
  - `web-front`：分析页与实时分析 UI 逻辑，避免在未点击实时分析时触发不必要的推理请求。
  - `docs/memo` 与 `docs/context`：记录每次 Triton/Graph 相关变更和决策，供后续调试与审计。

- **外部依赖（库/服务/硬件）：**
  - Triton Server（含 TensorRT backend）、CUDA Runtime 与 GPU 驱动。
  - MinIO S3 模型仓库与其配置（模型路径、bucket、访问凭据）。
  - MySQL `cv_cp` 与 Redis（用于订阅/配置状态持久化与缓存）。
  - 宿主机/容器中的 gdb、日志收集与监控栈（Prometheus/Grafana）。

---

# 风险清单（Top-5）

- **Triton/TensorRT backend 内部 bug 再次触发** → 触发条件：特定输出配置或 batch 形状下 In-Process 执行 → 监控信号：`InferenceResponse` 相关 SIGSEGV、`TRITONBACKEND_ResponseNew` 栈顶崩溃 → 预案：继续约束输出集合（固定 `output0` 等）、限制动态 shape 组合；在关键 Graph 中提供 provider 回退配置，并保留 ORT/CUDA 路径作为兜底。  
- **本地 ONNX 路径与 MinIO 仓库配置冲突** → 触发条件：provider 解析错误或 `pick_path_for` 返回本地路径 → 监控信号：`ONNX Runtime failed to load model ... File doesn't exist` 日志出现 → 预案：修正 `NodeModel` 和路径选择逻辑，使 provider='triton' 时只使用 `"__triton__"`；增加启动自检脚本，提前发现缺失的本地模型引用。  
- **前端行为与后端推理生命周期不一致** → 触发条件：分析页打开时错误地触发推理初始化或 warmup → 监控信号：未点击实时分析时 GPU 使用或 Triton 请求出现；VA 在此阶段崩溃 → 预案：与 Web-Front/CP 对齐接口约定，仅在明确的“开始实时分析”操作后触发推理；在 VA 端对无订阅/无实时分析状态下的推理请求做防御。  
- **per-node 输入/输出名配置漂移** → 触发条件：模型或 Triton config 更新后未同步修改 Graph 中 `triton_input`/`triton_outputs` → 监控信号：Triton 日志中出现 `unexpected inference input/output` 错误；VA 侧节点 open 失败 → 预案：在 Graph 校验阶段增加对 Triton metadata 的对比检查；为 det/reid 维护集中配置清单，变更时同步更新并写入 `docs/memo`。  
- **性能或资源回退策略不清晰** → 触发条件：In-Process 或 Triton backend 出现间歇性问题，需要临时关闭或回退 → 监控信号：推理失败率/延迟抖动明显增加；告警频繁 → 预案：为 In-Process/Trt provider 提供显式开关与 runtime fallback；在 `docker-compose` 与配置文件中预置 CPU/ORT 模式；在文档中写清推荐回退步骤和验证流程。  
