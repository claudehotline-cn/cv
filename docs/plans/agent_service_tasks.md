## Agent 服务任务清单（按阶段）

### Phase 1：MVP（单 ReAct Agent + 只读工具）

- T1.1 固化一期 Scope：仅支持 pipeline 列表/状态/基础指标查询，不做写操作
- T1.2 核对并锁定依赖版本，编写 `agent/requirements.txt`
- T1.3 在 `agent/cv_agent` 下创建基础目录结构与 `config.py`
- T1.4 实现与 CP 的只读 HTTP 客户端封装（基于 httpx），完成 list/get status 接口对接
- T1.5 基于 LangChain 1.0 + LangGraph-prebuilt 实现 `create_react_agent`：
  - 接入 Chat 模型（OpenAI 或兼容）
  - 注册 `list_pipelines`、`get_pipeline_status` 等只读工具
- T1.6 实现 FastAPI 接口 `/v1/agent/invoke`：
  - 接收 messages 与（可选）thread_id
  - 调用 ReAct agent，返回最终 AI 回复与必要的工具调用摘要
- T1.7 增加基础日志：记录请求、工具调用、CP 返回码与耗时
- T1.8 编写最小 E2E 测试（脚本或简单前端页面）验证“自然语言 → 工具调用 → CP 查询 → 回复”闭环
- T1.9 编写基础 README 和 API 使用说明

### Phase 2：更多工具 + 持久化 Checkpoint

- T2.1 梳理并确定需要在 agent 中支持的写操作列表（创建/更新/删除 pipeline、切模型、调 tracker 参数等）
- T2.2 为每个写操作接口设计工具签名、参数结构与 dry-run 输出格式（diff 结构）
- T2.3 在 CP 侧确认相关 API 的幂等性与错误码规范（确保工具可重试）
- T2.4 引入 LangGraph 持久化 checkpoint（SQLite/MySQL），实现线程级 state 存储
- T2.5 实现 `/v1/agent/threads/{thread_id}/invoke` 接口，支持多轮对话与上下文记忆
- T2.6 实现高危工具的人机协同流程：
  - 第一步：只执行 dry-run，生成计划和结构化 diff
  - 第二步：返回前端，由用户点击“确认/取消”
  - 第三步：携带 confirm 标记再次调用，执行真实写操作
- T2.7 扩展日志与审计：
  - 增加 thread_id、diff 摘要、confirm 信息
  - 在 CP 审计中增加 “triggered_by_agent” 字段
- T2.8 增强前端：支持线程列表、历史记录查看与变更确认界面
- T2.9 编写集成测试：覆盖 dry-run、确认、取消、异常回滚等场景

### Phase 3：自定义多 Agent StateGraph + RAG

- T3.1 设计 `AgentState` 结构（messages/user/cv_context/plan/pending_tools 等）
- T3.2 使用 `StateGraph` 定义 Router、PipelineAgent、DebugAgent、ModelAgent、ToolExecutor 等节点
- T3.3 将 Phase1/2 的工具接入新的多 Agent Graph，验证行为一致性
- T3.4 构建 RAG 知识库：
  - 选取 `docs/`、pipeline 配置样例、CP API 文档等作为语料
  - 搭建索引与检索器（向量或混合检索）
- T3.5 实现 `search_cv_docs` 等 RAG 工具，并将其纳入决策路径（先查文档，再执行工具）
- T3.6 在高复杂问题场景（排障、参数推荐）中引入 RAG + 多 Agent 协作，验证效果
- T3.7 补充高级使用文档与调优指南（如何新增工具、如何扩展知识库、如何调整路由策略）

