# 路线图总览

- **M0：Agent 工具链打通与错误收敛**
  - 目标：让 Agent 能稳定通过控制平面的工具获取真实 pipelines 状态，并在前端“思考流程”中体现完整的工具调用步骤。
  - 验收标准：
    - 针对“当前有哪些管线在运行”类问题，至少 80% 的请求会触发一次只读工具调用且返回可用数据。
    - 不再出现同步调用 async 工具的运行时错误（如之前的 StructuredTool 同步调用异常）。
    - `agent_data.steps` 中能稳定看到 user → thinking → tool → response 的完整链路。

- **M1：观测与调试能力增强**
  - 目标：为 Agent 工具链和 cp-spring 代理增加可观测性与调试支撑，使常见故障可以在分钟级定位。
  - 验收标准：
    - Agent 暴露 per-tool 调用次数、成功率、错误类型的聚合统计，并由 cp-spring 提供统一查询入口。
    - Grafana 上有覆盖 Agent / cp-spring / VA / VSM 的联动视图，可快速关联 HTTP 错误与 gRPC 失败。
    - 通过 Chrome DevTools MCP 或自动化脚本，能够一键重放典型场景并导出用于回归的“行为证据”。

- **M2：前端体验与策略优化**
  - 目标：提升 Agent 控制台的可解释性与易用性，让用户清楚知道答案来源（实时数据 vs 文档推理），并降低误用风险。
  - 验收标准：
    - 前端 Agent 页面能显式区分“调用过工具的回答”和“仅基于历史/文档推理的回答”。
    - 高危操作（删除 / 热切换 / drain）仍受 plan+confirm 流程保护，并在 UI 上有清晰提示。
    - 有一套通过 UI 驱动的回归用例（脚本化或手册化），覆盖典型查询与控制路径。

---

# 分阶段计划（表格）

| 阶段 | 关键交付物 | 技术要点 | 风险/缓解 | 指标门槛 |
|---|---|---|---|---|
| P0：现状固化 | 更新 CONTEXT/ROADMAP，梳理系统提示与工具链现状 | 明确 cp-spring 注入的系统提示词是权威源，Python Agent 不再二次注入 | 文档与实现偏差 → 通过代码引用检查与审核确保一致 | 文档覆盖当前实现的 90% 关键行为 |
| P1：工具调用可靠化（对 pipelines 查询） | 修复 pipelines 查询相关的工具调用路径，让查询问题优先实际访问后台 | 优化 StateGraph 节点逻辑与提示词 few-shot，引导在实时状态问题上优先调用工具，避免因历史失败直接放弃 | 工具本身异常或 CP 不可用 → 在工具层和 Agent 层分别返回可区分的错误，并为 CP 故障提供快速探针脚本 | 面向 pipelines 查询的请求中，工具调用成功率 ≥ 80% |
| P2：Agent 指标与统计 | Agent 提供工具调用与递归限制相关的统计接口 | 在 Agent 内部聚合 per-thread / per-tool 统计，cp-spring 代理聚合视图；区分“未调用工具”和“调用失败”两种情况 | 指标与真实行为不一致 → 定期用 DevTools MCP/脚本对比统计与真实日志 | 每种工具都有 QPS / 成功率 / 错误率指标 |
| P3：前端体验增强 | 前端 Agent 控制台显示答案来源与工具使用情况 | 将 `agent_data.steps` 映射为 UI 标签（如“已使用控制平面工具”），并在未调用工具时给出轻量提示 | UI 信息过多影响易用性 → 通过 A/B 或内部评审简化标签文案 | 用户能直观区分“实时数据回答”与“推理回答” |
| P4：自动化回归与多环境对齐 | 基于典型场景的自动化回归（前端 + Agent + cp-spring） | 结合 Python 脚本、DevTools MCP 或 Playwright，对 pipelines 查询与控制操作形成可重放用例 | 多环境配置差异 → 在 CONTEXT 中记录关键环境变量与端点，对 dev/stage/prod 进行比对 | 关键场景回归脚本在所有环境通过率 ≥ 95% |

---

# 依赖矩阵

- 内部依赖：
  - **cp-spring**：提供 `/api/agent/*` 代理与系统提示注入，是 Agent 对外的唯一入口。
  - **cv_agent（Python）**：实现 StateGraph、工具执行和 `agent_data` 构建，是工具链逻辑中枢。
  - **video-analyzer（VA）**：提供 pipelines 状态与控制 RPC，工具依赖其 HTTP/gRPC 接口返回真实状态。
  - **video-source-manager（VSM）**：在涉及源管理与健康检查的 Agent 能力中参与调用。
  - **web-frontend**：`/agent` 页面负责承载对话界面和“思考流程”可视化，是用户认知的主要窗口。

- 外部依赖（库/服务/硬件）：
  - LangChain / LangGraph 及其工具封装机制（特别是 async StructuredTool 与 `ainvoke` 行为）。
  - OpenAI / Ollama LLM 服务（用于 Agent 与文档检索），网络和配额会直接影响 Agent 的响应质量。
  - MySQL、Redis、Prometheus、Grafana 等基础设施，用于配置存储、缓存与监控。
  - GPU 服务器与 RTSP 摄像头，确保 pipelines 实际可运行并产生状态数据。

---

# 风险清单（Top-5）

- 工具未触发但用户误以为使用了实时数据  
  → 触发条件：LLM 在复杂或多轮失败上下文中倾向仅给解释性回答  
  → 监控信号：`agent_data.steps` 中长时间缺少 `type=tool` 记录，但 pipelines 查询请求量较高  
  → 预案：强化提示词与 few-shot，增加“答案来源标签”和统计指标，对未触发工具的场景进行专门回归。

- 控制平面或 VA/VSM 不可用导致工具失败  
  → 触发条件：cp-spring→VA/VSM 或 Agent→cp-spring 的请求出现持续 5xx/超时  
  → 监控信号：gRPC/HTTP 错误率、工具失败率飙升，日志中出现集中错误码  
  → 预案：在工具层返回结构化错误并提示用户是“系统故障”，同时在 Dashboard 上提供一键健康检查视图。

- 递归深度限制过于保守导致早停  
  → 触发条件：复杂问题在 StateGraph 内反复 agent→tools→agent 但未能完成一次有效工具调用  
  → 监控信号：`GraphRecursionError` 计数增加，用户频繁看到“步数超过上限”提示  
  → 预案：在工具链修复后适当提升递归上限，或在递归接近上限时更强制地尝试一次工具调用而不是继续思考。

- 文档与实现漂移导致运维误判  
  → 触发条件：CONTEXT/ROADMAP 未及时更新，或配置变更未记录  
  → 监控信号：排障时需要频繁查看源码才能确认行为，文档描述与实际返回结构不一致  
  → 预案：将文档更新纳入变更流程（含 memo 记录），定期以脚本校验关键端点行为。

- 前端/DevTools 测试环境与生产不一致  
  → 触发条件：WSL headless Chrome 与实际用户浏览器、或 dev 与 prod 的 API base URL 配置不一致  
  → 监控信号：DevTools 测试通过但线上用户仍反馈错误；同一操作在不同环境得到不同结果  
  → 预案：在 CONTEXT 中固定记载各环境的访问路径与关键 env，增加统一的环境自检脚本，并在发布前针对多环境跑一轮标准化 DevTools 回归。

