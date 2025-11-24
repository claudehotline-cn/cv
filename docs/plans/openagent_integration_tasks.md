## openAgent 借鉴集成任务清单

### Phase A：调研与对齐

- TA1 分析 openAgent 后端架构（services/agent、services/knowledge、smart_query 等），形成对比文档，标注与 CV 项目可复用/可借鉴点。
- TA2 明确本项目 Agent 的边界：列出“必须做 / 可以不做”的能力列表，避免引入不必要复杂度。

### Phase B：Agent 编排（StateGraph 化）

- TB1 设计并实现 `AgentState` 类型，包含 messages/user/cv_context/plan/pending_tools 等核心字段。
- TB2 在 `cv_agent.graph` 下新增 StateGraph 实现：Router、PipelineAgent、DebugAgent、ModelAgent、ToolExecutor。
- TB3 将现有 ReAct agent 的工具调用逻辑迁移到 StateGraph，确保现有 `/v1/agent/invoke` 行为兼容。
- TB4 增加基础控制流特性：错误重试、条件分支（例如根据 op 分派到不同子 Agent）。

### Phase C：工具体系与 Registry

- TC1 在 `cv_agent.tools` 下引入 ToolRegistry 概念：统一注册 list/get/status/plan/execute 等工具。
- TC2 为每个工具增加元数据（只读/高危、所属域：pipeline/va/debug/metrics 等）。
- TC3 调整 Agent 编排代码改为通过 Registry 取工具，而不是直接 from/import。
- TC4 设计 MCP 接入草案（接口定义与部署拓扑），暂不落地实现。

### Phase D：知识库与 RAG 集成

- TD1 梳理 `docs/` 中适合纳入知识库的文档（设计文档、调参指南、错误分析、FAQ）。
- TD2 选定向量存储方案（复用 MySQL + 向量插件或独立存储），实现最小分片+嵌入+写入 pipeline。
- TD3 实现 `search_cv_docs(query)` 工具，返回结构化文档片段（标题/路径/摘要）。
- TD4 在 Agent 编排中加入“RAG 决策节点”：在处理复杂问题时先调用 `search_cv_docs`，再决定后续工具调用。

### Phase E：Agent UI 与交互增强

- TE1 基于当前 `Agent.vue`，设计更完整的 chat UI：消息流、工具调用步骤、control_result 展示区域。
- TE2 为 pipelines/detail 页面设计一个嵌入式 Agent 面板，默认 thread_id 绑定当前 pipeline。
- TE3 在前端提供线程列表视图（按 pipeline/thread_id 聚合），方便回看历史对话与操作。
- TE4 优化错误提示与 loading 状态，让运维可以在 UI 中清晰看到 plan/execute 的状态与结果。

### Phase F：线程/审计/运维一体化

- TF1 规范化 `thread_id` 命名策略，在 Agent/CP/前端保持一致（如 pipeline:xxx、drain:xxx、deploy:xxx）。
- TF2 扩展 checkpoint 存储结构，使其可按用户/thread_id 查询历史对话摘要和最后一次控制操作状态。
- TF3 在 CP 审计日志中增加 Agent 相关字段（thread_id/op/mode/confirm/结果摘要），并记录到现有日志管线。
- TF4 在 Observability or 新页面中展示 Agent 的控制操作统计（按 op/thread/pipeline 聚合）。

