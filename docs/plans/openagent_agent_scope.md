## openAgent 集成下本项目 Agent 边界（TA2）

本说明文档用于落实 `openagent_integration_tasks.md` 中 Phase A-TA2 任务：**明确本项目 Agent 的边界，列出“必须做 / 可以不做”的能力列表，避免引入不必要的复杂度。**

---

## 1. 总体定位

- Agent 的角色：**面向运维/开发的“智能控制与排障助手”**，负责理解自然语言意图，编排 CP/VA/VSM 等后端能力，不承担账号体系、通用聊天平台等职责。
- 权责边界：
  - **只通过 CP API 进行配置变更**（CP 是唯一真相源），禁止直接写业务数据库。
  - 对 VA 仅做状态/运行信息查询，不绕过 CP 直接修改推理配置。
  - 对外服务面向“内部运维/开发人员”，不面向终端用户。

---

## 2. 必须做的能力（Must-have）

这些能力是当前路线图（Agent 服务任务清单 + openAgent 集成 WBS）中 **必须交付** 的功能，缺失会直接影响运维效率或控制面的可用性。

1. **Pipeline 可观测性与基本控制**
   - 列出当前所有 pipeline（名称、graph、模型、状态等）。
   - 查询单个 pipeline 的运行状态和关键指标（phase、错误计数、最近事件概览）。
   - 通过控制协议执行以下高危操作（严格 plan → execute 流程）：
     - `pipeline.delete`：删除 pipeline；
     - `pipeline.hotswap`：模型热切换；
     - `pipeline.drain`：drain pipeline。
   - 所有写操作必须：
     - 先通过 `plan_*` 工具生成结构化 diff/计划；
     - 前端基于 `control_result` 展示计划并要求显式确认；
     - 确认后才调用 `mode=execute & confirm=true`。

2. **CP/VA/VSM 只读查询与排障辅助**
   - 通过工具从 CP 查询：
     - models / pipelines / graphs 列表与配置；
     - subscriptions / sources / orch（编排）相关只读状态；
     - system.info / metrics / va.runtime 等观测接口。
   - 在 Agent 回复中对这些结构化结果进行**自然语言总结**，帮助运维快速理解当前状态。

3. **基于 StateGraph 的可扩展编排骨架**
   - 在 `cv_agent.graph` 中提供基于 `AgentState` 的 StateGraph 实现，支持：
     - 多节点编排（Router / PipelineAgent / DebugAgent / ModelAgent / ToolExecutor 等）；
     - 工具调用闭环（LLM 产生 tool_calls → ToolExecutor 执行 → ToolMessage 反馈）。
   - 通过 checkpoint（memory/sqlite）按 `thread_id` 维度保存对话与控制上下文。

4. **高危操作的人机协同与审计**
   - 强制所有 delete/hotswap/drain 等高危操作走 plan+confirm 模式。
   - 在 Agent 与 CP 侧的日志/审计中记录：
     - `thread_id` / `user_id` / `op` / `mode` / `confirm` / 结果摘要。
   - 为后续在 cp-spring / 前端中按线程/操作回放历史提供基础数据。

5. **基础 RAG 能力（面向本项目文档）**
   - 将 `docs/` 中与 CP/VA/Agent 相关的关键文档纳入知识库（分片 + 嵌入 + 存储）。
   - 提供 `search_cv_docs(query)` 工具，返回标题/路径/片段等结构化结果。
   - 在复杂排障/配置问题场景中，Agent 能够：
     - 先检索相关文档片段；
     - 在回答中引用或总结这些片段，减少“拍脑袋”回答。

---

## 3. 可以不做 / 暂不纳入范围的能力（Nice-to-have）

以下能力在 openAgent 中已有实践，但对于当前 CV 项目属于 **可选能力**，仅在明确业务价值和资源后再考虑：

1. **通用聊天 / 闲聊能力**
   - 不要求 Agent 具备开放式闲聊或通用问答能力；
   - 默认不对接通用知识库（例如互联网搜索、百科），避免干扰运维场景。

2. **全功能工作流编排与长周期任务管理**
   - 不以 openAgent 的“工作流/任务编排引擎”为目标；
   - 当前阶段仅关注控制面相关的短流程（plan→execute）和少数多步排障建议；
   - 对跨天/跨周的长周期任务（如自动化巡检、定期报表）不由 Agent 直接负责，可由独立任务系统承担。

3. **复杂账号/租户/权限体系**
   - Agent 不单独实现用户、角色、租户管理；
   - 依赖外部（如 CP / 上游网关）完成认证与粗粒度授权；
   - 通过请求头透传 `X-User-Id` / `X-User-Role` / `X-Tenant` 等，用于日志与审计，不在 Agent 内部实现细粒度 RBAC。

4. **直接访问数据库或外部业务系统**
   - Agent 不直接读写 CP 业务数据库，也不通过 MCP/直连方式修改外部业务系统；
   - 若未来需要对接 MySQL/Prometheus/日志系统等，应通过：
     - CP 提供的受控 API；
     - 或专门的 MCP 工具服务，在明确权限与审计方案后再引入。

5. **高频实时决策或在线 Auto Tuning**
   - Agent 不用于每秒级/每帧级的实时决策（如在线调参、自适应策略）；
   - 仅在“人工触发的运维操作”场景下提供建议与执行，避免引入难以控制的自动化行为。

---

## 4. 约束与后续演进建议

- 在未来扩展 Agent 能力（新增工具 / 接入更多后端服务）时，应先对照本边界文档评估：
  - 是否属于上述 Must-have 范畴；
  - 是否需要在 CP/VA 侧补充接口与审计能力；
  - 是否需要更新 `docs/plans/openagent_integration_tasks.md` 与相关 WBS。
- 如需突破本文件中“可以不做”的范围，应先在设计文档中给出动机、风险分析与回滚方案，再进入实施阶段。

