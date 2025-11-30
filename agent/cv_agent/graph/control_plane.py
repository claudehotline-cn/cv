from typing import Any, List, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent

from ..config import get_settings
from ..store import get_checkpointer
from ..tools import get_all_tools
from ..tools.rag import SearchCvDocsInput, search_cv_docs_tool
from .state_graph import AgentState

_CONTROL_PLANE_AGENT: Any | None = None
_STATEGRAPH_AGENT: Any | None = None


def _build_agent() -> Any:
    """Construct the ReAct-style control-plane agent graph (prebuilt)."""

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "openai").lower()
    if provider == "ollama":
        model = ChatOllama(
            model=settings.llm_model,
            base_url=getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
        )
    else:
        model = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
    tools = get_all_tools()
    checkpointer = get_checkpointer()
    agent_graph = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=checkpointer,
    )
    return agent_graph


def _build_stategraph_agent() -> Any:
    """
    Construct a multi-node StateGraph-based control-plane agent.

    当前实现包含 Router / PipelineAgent / DebugAgent / ModelAgent / ToolExecutor 等节点：
    - Router：根据最近一条用户消息粗略判断意图（pipeline/debug/model），写入 state.task；
    - *Agent：调用 LLM（带工具描述），生成回复与 tool_calls；
    - ToolExecutor：解析 tool_calls 并顺序执行工具，将结果以 ToolMessage 形式追加到消息流中。

    该图保持与预构建 ReAct Agent 相同的基本行为（agent→tools→agent 循环），
    但在结构上为后续拆分子 Agent 与引入更多控制流提供扩展点。
    """

    settings = get_settings()
    provider = getattr(settings, "llm_provider", "openai").lower()
    if provider == "ollama":
        model = ChatOllama(
            model=settings.llm_model,
            base_url=getattr(settings, "ollama_base_url", "http://host.docker.internal:11434"),
        )
    else:
        model = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
    tools = get_all_tools()

    try:
        bound_model = model.bind_tools(tools)
    except Exception:
        bound_model = model

    graph = StateGraph(AgentState)

    def _copy_state_with(
        state: AgentState,
        *,
        messages: List[BaseMessage],
        task: str | None = None,
    ) -> AgentState:
        """在保持除 messages/task 以外字段不变的前提下构造新的 AgentState。"""

        return AgentState(
            messages=messages,
            user=state.user,
            cv_context=state.cv_context,
            plan=state.plan,
            pending_tools=state.pending_tools,
            task=task if task is not None else state.task,
            last_control_op=state.last_control_op,
            last_control_mode=state.last_control_mode,
            last_control_result=state.last_control_result,
        )

    def router_node(state: AgentState) -> AgentState:
        """
        Router 节点：根据最近一条用户消息简单判断意图，并写入 state.task。

        目前仅做粗粒度分类：
        - 默认：pipeline；
        - 包含“日志/错误/error/metrics”等关键词：debug；
        - 包含“模型/model/训练”等关键词：model。
        """

        msgs: List[BaseMessage] = list(state.messages)
        task = state.task or "pipeline"

        # 简单从最近一条 HumanMessage 中推断意图
        for msg in reversed(msgs):
            if isinstance(msg, HumanMessage):
                text = str(getattr(msg, "content", "") or "")
                lowered = text.lower()
                if any(k in text for k in ("日志", "错误")) or any(
                    k in lowered for k in ("log", "error", "metrics")
                ):
                    task = "debug"
                elif any(k in text for k in ("模型", "训练")) or any(
                    k in lowered for k in ("model", "train")
                ):
                    task = "model"
                else:
                    task = "pipeline"
                break

        return _copy_state_with(state, messages=msgs, task=task)

    def _agent_step(state: AgentState, *, agent_kind: str) -> AgentState:
        """通用 Agent 节点步骤：调用 LLM，生成一条回复。"""

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            # 没有历史消息时不调用模型，直接返回
            return state

        reply = bound_model.invoke(msgs)
        if not isinstance(reply, BaseMessage):
            reply = AIMessage(content=str(reply))
        msgs.append(reply)

        return _copy_state_with(state, messages=msgs, task=agent_kind)

    def pipeline_agent_node(state: AgentState) -> AgentState:
        """负责 pipeline 相关对话与工具触发的 Agent 节点。"""

        return _agent_step(state, agent_kind="pipeline")

    def debug_agent_node(state: AgentState) -> AgentState:
        """负责日志/错误排障相关对话的 Agent 节点（当前实现与 pipeline 行为一致）。"""

        return _agent_step(state, agent_kind="debug")

    def model_agent_node(state: AgentState) -> AgentState:
        """负责模型/训练相关对话的 Agent 节点（当前实现与 pipeline 行为一致）。"""

        return _agent_step(state, agent_kind="model")

    def tool_executor_node(state: AgentState) -> AgentState:
        """
        工具执行节点：读取最后一条 AIMessage 中的 tool_calls，并顺序执行对应工具。

        工具执行结果通过 ToolMessage 追加到消息流中，供下一轮 Agent 再次思考。
        """

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            return state

        last = msgs[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if not tool_calls:
            return state

        name_to_tool = {getattr(t, "name", None): t for t in tools}
        outputs: List[ToolMessage] = []

        for call in tool_calls:
            if isinstance(call, dict):
                name = call.get("name")
                args = call.get("args") or {}
                call_id = call.get("id") or ""
            else:
                name = getattr(call, "name", None)
                args = getattr(call, "args", {}) or {}
                call_id = getattr(call, "id", "") or ""

            if not name:
                result = "Tool call missing name"
            else:
                tool_impl = name_to_tool.get(name)
                if not tool_impl:
                    result = f"Unknown tool: {name}"
                else:
                    try:
                        # LangChain 工具统一通过 invoke 调用
                        result = tool_impl.invoke(args)
                    except Exception as exc:  # pragma: no cover - 运行时保障
                        result = f"Tool {name} execution error: {exc}"

            outputs.append(
                ToolMessage(
                    content=str(result),
                    tool_call_id=call_id,
                )
            )

        msgs.extend(outputs)

        # ToolExecutor 不修改 task，仅追加工具执行结果
        return _copy_state_with(state, messages=msgs)

    def _should_apply_rag(text: str) -> bool:
        """根据用户提问内容判断是否需要预先检索文档。"""

        if len(text.strip()) < 10:
            return False

        lowered = text.lower()
        keywords_cn = ("文档", "说明", "配置项", "参数", "含义", "错误码", "怎么配置", "如何配置")
        keywords_en = ("doc", "docs", "documentation", "config", "parameter", "meaning", "error code")
        if any(k in text for k in keywords_cn):
            return True
        if any(k in lowered for k in keywords_en):
            return True
        return False

    def rag_node(state: AgentState) -> AgentState:
        """
        RAG 决策节点：

        - 从最近一条用户消息中提取 query；
        - 在知识库中调用 `search_cv_docs` 检索相关片段；
        - 将简要结果以 SystemMessage 形式追加到对话中，供后续 Agent 节点参考。
        """

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            return state

        last_user: HumanMessage | None = None
        for msg in reversed(msgs):
            if isinstance(msg, HumanMessage):
                last_user = msg
                break

        if last_user is None:
            return state

        query = str(getattr(last_user, "content", "") or "")
        if not _should_apply_rag(query):
            return state

        summary = ""
        try:
            params = SearchCvDocsInput(query=query)
            results = search_cv_docs_tool.invoke(params)
            if not results:
                summary = "知识库中未找到与当前问题明显相关的文档片段。"
            else:
                lines: List[str] = ["以下是与当前问题可能相关的文档片段："]
                for row in results[:3]:
                    title = row.get("title") or ""
                    path = row.get("path") or ""
                    snippet = (row.get("snippet") or "")[:200]
                    lines.append(f"- [{title}]({path}): {snippet}")
                summary = "\n".join(lines)
        except Exception as exc:  # pragma: no cover - 运行时防御
            summary = f"尝试从知识库检索文档时出错：{exc}"

        if not summary:
            return state

        msgs.append(SystemMessage(content=summary))
        new_ctx = dict(state.cv_context or {})
        new_ctx["rag_applied"] = True
        return AgentState(
            messages=msgs,
            user=state.user,
            cv_context=new_ctx,
            plan=state.plan,
            pending_tools=state.pending_tools,
            task=state.task,
            last_control_op=state.last_control_op,
            last_control_mode=state.last_control_mode,
            last_control_result=state.last_control_result,
        )

    def route_from_router(state: AgentState) -> str:
        """Router 之后，根据 state.task 决定进入哪个子 Agent。"""

        task = (state.task or "pipeline").lower()
        if task == "debug":
            return "debug"
        if task == "model":
            return "model"
        return "pipeline"

    def route_after_agent(state: AgentState) -> str:
        """Agent 节点之后，根据是否存在 tool_calls 决定走 ToolExecutor 还是结束。"""

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            return END
        last = msgs[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if tool_calls:
            return "tools"
        return END

    # 定义节点
    graph.add_node("router", router_node)
    graph.add_node("rag", rag_node)
    graph.add_node("pipeline_agent", pipeline_agent_node)
    graph.add_node("debug_agent", debug_agent_node)
    graph.add_node("model_agent", model_agent_node)
    graph.add_node("tool_executor", tool_executor_node)

    # 边与控制流：
    # START → router → rag → {pipeline_agent | debug_agent | model_agent}
    graph.add_edge(START, "router")
    graph.add_conditional_edges(
        "rag",
        route_from_router,
        {
            "pipeline": "pipeline_agent",
            "debug": "debug_agent",
            "model": "model_agent",
        },
    )
    graph.add_edge("router", "rag")

    # 各 Agent 节点 → 根据 tool_calls 决定进入 ToolExecutor 或结束
    for agent_name in ("pipeline_agent", "debug_agent", "model_agent"):
        graph.add_conditional_edges(
            agent_name,
            route_after_agent,
            {
                "tools": "tool_executor",
                END: END,
            },
        )

    # ToolExecutor 执行完工具后回到 Router，形成 agent→tools→router→agent... 的循环
    graph.add_edge("tool_executor", "router")

    checkpointer = get_checkpointer()
    return graph.compile(checkpointer=checkpointer)


def get_control_plane_agent() -> Any:
    """Return a singleton prebuilt ReAct-style control-plane agent."""

    global _CONTROL_PLANE_AGENT
    if _CONTROL_PLANE_AGENT is None:
        _CONTROL_PLANE_AGENT = _build_agent()
    return _CONTROL_PLANE_AGENT


def get_stategraph_agent() -> Any:
    """Return a singleton StateGraph-based control-plane agent."""

    global _STATEGRAPH_AGENT
    if _STATEGRAPH_AGENT is None:
        _STATEGRAPH_AGENT = _build_stategraph_agent()
    return _STATEGRAPH_AGENT


def build_state_from_tuples(
    messages: List[Tuple[str, str]],
) -> dict:
    """
    Build LangGraph state dict from (role, content) tuples.

    兼容预构建 ReAct Agent 的输入格式：
        { "messages": [("user", "…"), ("assistant", "…")] }
    """

    return {"messages": messages}
