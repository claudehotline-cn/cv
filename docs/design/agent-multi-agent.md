# 控制平面 Agent 多 Agent 拆分设计（P3）

本文档对应 `agent_tasks` / `agent_wbs` 中的「10. 多 Agent 拆分与更细粒度任务路由」，描述 Python `cv_agent` 当前的多 Agent 结构、Router 策略以及后续演进方向。

## 1. 总体结构

当前 Python Agent 通过 `cv_agent.graph.control_plane._build_stategraph_agent()` 构建一张基于 LangGraph `StateGraph` 的有向图，围绕统一的 `AgentState` 组织多个“子 Agent”节点：

- **Router 节点**
  - 入口节点，读取最近一条用户消息，粗粒度判断意图，并写入 `state.task`：
    - 默认：`pipeline`
    - 包含“日志/错误/log/error/metrics”等关键词：`debug`
    - 包含“模型/model/训练/train”等关键词：`model`
- **Pipeline Agent 节点**
  - 负责 pipeline 管理相关对话与工具调用（例如 list_pipelines / get_pipeline_status / pipeline.drain）。
- **Debug Agent 节点**
  - 面向日志与故障排查场景（未来可接入 metrics/logs 专用工具）；当前与 pipeline Agent 共用模型与工具集合，仅通过 `state.task="debug"` 区分语义。
- **Model Agent 节点**
  - 面向模型与训练任务（训练作业管理、模型评估等）；当前为预留入口，同样复用主模型与工具集合。
- **RAG 决策节点**
  - 根据最近一条用户消息中是否出现“文档/说明/config/parameter/错误码”等关键词决定是否调用 `search_cv_docs`，并将检索到的片段以 `SystemMessage` 的形式注入到 `state.messages` 中，供后续 Agent 节点使用。
- **ToolExecutor 节点**
  - 读取最后一条 `AIMessage.tool_calls`，根据工具名找到对应 LangChain Tool，顺序执行并将结果以 `ToolMessage` 追加到 `state.messages`。

所有子 Agent 与节点共享同一个 `AgentState`：

- `messages: List[BaseMessage]`：对话与工具消息流；
- `user: Dict[str, Any]`：`user_id/role/tenant` 等上下文；
- `cv_context: Dict[str, Any]`：例如 `{"rag_applied": true}`；
- `plan: List[str]` / `pending_tools: List[Dict[str,Any]]`：后续可用于显式计划；
- `task: Optional[str]`：当前路由意图（pipeline/debug/model）；
- `last_control_*`：最近一次控制操作摘要。

## 2. Router 与多 Agent 路由策略

### 2.1 Router 规则

Router 节点遍历 `state.messages` 中最近的用户消息，并根据内容设置 `state.task`：

- 若包含中文“日志/错误”或英文 `"log"/"error"/"metrics"` → `debug`
- 若包含中文“模型/训练”或英文 `"model"/"train"` → `model`
- 否则默认为 `pipeline`

该逻辑目前实现于 `router_node()`，并在 StateGraph 中通过：

- `START -> router -> rag -> {pipeline_agent, debug_agent, model_agent}` 这一条主路径落地；
- `route_from_router()` 根据 `state.task` 将执行流分发到不同 Agent 节点。

### 2.2 Agent 节点行为

三个 Agent 节点 `pipeline_agent/debug_agent/model_agent` 目前共用同一套行为：

- 调用统一的 Chat LLM（OpenAI/Ollama），附带工具描述；
- 对异常做简单重试与降级处理（两次失败后返回错误提示消息）；
– 将回复追加到 `state.messages` 并更新 `state.task=agent_kind`。

ToolExecutor 节点则负责解析工具调用并执行具体 Tool：

- 优先使用 Tool 的 `ainvoke()`，否则回退到同步 `invoke()`；
- 对异常记录 warning 日志，并通过 `record_tool_call()` 记录工具名、成功标志与耗时；
- 执行结果以 `ToolMessage` 形式追加到 `state.messages`，随后通过 `tool_executor -> router` 的边回到 Router，形成 `agent -> tools -> router -> agent` 的循环。

## 3. 测试与回归

围绕 Router 与多 Agent 路由，已经补充了以下基础测试（见 `agent/tests`）：

- **Router 任务分流**
  - `agent/tests/test_router_and_fallbacks.py::test_router_sets_task_based_on_user_message`：
    - 使用 `_DummySettingsRouter` 与 `_DummyLLM` 替代实际 LLM 调用；
    - 调用 `_invoke_stategraph_agent()` 后断言返回的 `state["task"]` 与输入语义对应（pipeline/debug/model）。
- **StateGraph 递归上限回退**
  - `agent/tests/test_stategraph_recursion.py::test_invoke_stategraph_agent_recursion_error_returns_friendly_message`：
    - 通过 `_DummyGraph` 强制抛 `GraphRecursionError`，验证 `_invoke_stategraph_agent()` 会返回带有“超过上限”提示的 AI 消息，而不是直接抛异常。
- **INVALID_CHAT_HISTORY 自愈**
  - `agent/tests/test_router_and_fallbacks.py::test_invoke_agent_graph_invalid_chat_history_recovers`：
    - 使用 `_DummyGraphInvalidHistory` 模拟第一次抛 `"Found AIMessages with tool_calls"` 的 `ValueError`，第二次返回正常 state；
    - 验证 `_invoke_agent_graph()` 会自动重建 `thread_id`（第二次以 `reset-` 开头）并返回正常结果。

上述测试并未把 Pipeline/Debug/Model Agent 拆成完全独立子图，而是验证现有 Router + 多 Agent 节点结构在 P3 之前是稳定可用的。后续如需进一步拆分职责，可以在 StateGraph 中为每个 Agent 构建子图并引入特定工具集合。 

## 4. 未来演进方向

在当前多 Agent 基础上，后续可按以下方向进一步演进：

1. **细化 Pipeline/Debug/Model Agent 职责**  
   - Pipeline Agent：只挂载 pipeline 管理相关 Tool（list/status/drain/hotswap 等）；  
   - Debug Agent：引入日志/指标专用 Tool（如 VA/CP metrics 查询、最近错误日志抓取）；  
   - Model Agent：挂载训练作业管理与模型评估 Tool。

2. **按 Agent 维度拆分系统提示与 LLM 配置**  
   - 为不同 Agent 注入差异化 system prompt（例如 Debug Agent 更关注故障诊断步骤）；  
   - 在配置层支持为不同 Agent 选择不同模型（如 Debug Agent 使用更擅长长上下文分析的模型）。

3. **更精细的路由策略与反馈闭环**  
   - Router 除基于关键词外，可引入轻量分类模型或规则引擎；  
   - 为 Router/Agent 节点记录更多统计（按 task 维度的 QPS、错误率等），为后续调优路由策略提供数据基础。

4. **子图与可视化**  
   - 将 Pipeline/Debug/Model Agent 各自的内部流程拆分为子图，利用 LangGraph 的可视化能力展示；  
   - 在前端 Agent 控制台中按 Agent 维度展示时间线与工具调用分布。

当前实现已经满足 `agent_tasks` 中「让 StateGraph 成为主 Agent 路径」以及 P3 阶段的基础多 Agent 拆分需求，后续演进可以在不破坏现有 HTTP API 的前提下逐步落地上述计划。 

