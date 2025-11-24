## openAgent 借鉴集成 WBS（按阶段）

### 1. 目标与范围澄清

- 1.1 明确与 openAgent 的差异：保留现有 VA/CP/Web/Agent 架构，不引入其账号体系与全套业务功能，仅借鉴 Agent 编排、工具体系、RAG 与 UI 交互。
- 1.2 确认本项目中 Agent 的核心职责边界：专注于 CP/VA 控制、排障与运维协助，而非通用问答平台。
- 1.3 定义第一阶段可交付物：StateGraph 化的 Agent、面向运维的 Agent 控制台、基础知识库 RAG。

### 2. Agent 编排与 StateGraph 升级

- 2.1 梳理当前 `cv_agent.graph.control_plane` 的 ReAct 逻辑与工具调用路径。
- 2.2 设计 `AgentState`（messages/user/cv_context/plan/pending_tools 等）结构。
- 2.3 定义 StateGraph 节点：Router、PipelineAgent、DebugAgent、ModelAgent、ToolExecutor。
- 2.4 将现有 ReAct agent 迁移到 StateGraph 实现，确保行为兼容。
- 2.5 基于 StateGraph 支持更多控制流模式（条件分支、错误重试、可插拔子流程）。

### 3. 工具抽象与 MCP 规划

- 3.1 分析 openAgent 的 ToolRegistry 与 MCP 动态工具机制。
- 3.2 为本项目设计 `ToolRegistry` 接口：注册、查找、分组、权限标记（只读/高危）。
- 3.3 梳理 CP/VA/监控工具清单，统一通过 Registry 管理。
- 3.4 设计 MCP 接入方案（中长期）：规划将 DB/外部服务封装为 MCP 工具的路径。

### 4. 知识库与 RAG 集成

- 4.1 选定需要纳入知识库的文档范围（`docs/`、配置样例、错误 FAQ 等）。
- 4.2 设计文档处理流水线：分片、清洗、嵌入、存储（MySQL/pgvector/SQLite+向量库）。
- 4.3 定义 RAG 工具接口：如 `search_cv_docs(query)`，输出精简上下文。
- 4.4 在 Agent 编排中引入“先 RAG 再调用工具”的决策模式。

### 5. Agent 前端 UI 演进

- 5.1 基于 openAgent 的 chat 界面，规划 CV 运维场景下的 Agent 控制台能力（控制操作、排障问答、知识库问答）。
- 5.2 丰富现有 `Agent.vue`：消息流、工具调用步骤可视化、control_result 结构化展示。
- 5.3 为 pipelines/detail 等页面规划嵌入式 Agent 面板（按 pipeline/thread 维度绑定）。

### 6. 线程管理与审计增强

- 6.1 结合 openAgent 的会话模型，为本项目规范 `thread_id` 命名（按 pipeline/任务类型等维度）。
- 6.2 扩展 checkpoint（SQLite/MySQL）以支持按 thread_id 查询历史对话与控制操作。
- 6.3 与 CP 审计日志联动：增加“triggered_by_agent + thread_id + op”字段。
- 6.4 在前端提供按 thread/pipeline 查看历史操作记录的视图。

### 7. 智能问数与工作流（中长期规划）

- 7.1 参考 openAgent 的 smart_query 模块，评估在 CV 运维场景引入“运维问数”（查询 CP/VA 状态、错误分布、订阅信息）的必要性。
- 7.2 设计最小运维问数能力：围绕 CP 的 MySQL/metrics/日志提供自然语言查询接口。
- 7.3 为后续 Agent 工作流（多步控制+验证）预留接口，与现有 YAML pipeline/业务工作流对齐。

