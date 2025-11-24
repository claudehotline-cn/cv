from typing import Any, List, Tuple

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langchain_openai import ChatOpenAI
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import create_react_agent

from ..config import get_settings
from ..store import get_checkpointer
from ..tools import get_all_tools
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
    Construct a minimal StateGraph-based control-plane agent.

    当前实现作为 StateGraph 化的起点，仅包含一个简单的 agent 节点：
    - 输入：AgentState（其中 messages 为 BaseMessage 列表）；
    - 行为：将当前消息序列交给 LLM，追加模型回复后返回新的 AgentState。

    后续可以在此基础上扩展 Router / PipelineAgent / DebugAgent / ToolExecutor 等节点。
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

    def agent_node(state: AgentState) -> AgentState:
        """核心 Agent 节点：调用 LLM（带工具描述），决定是否需要调用工具。"""

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            # 没有历史消息时不调用模型，直接返回
            return state

        reply = bound_model.invoke(msgs)
        if not isinstance(reply, BaseMessage):
            reply = AIMessage(content=str(reply))
        msgs.append(reply)

        return AgentState(
            messages=msgs,
            user=state.user,
            cv_context=state.cv_context,
            plan=state.plan,
            pending_tools=state.pending_tools,
            last_control_op=state.last_control_op,
            last_control_mode=state.last_control_mode,
            last_control_result=state.last_control_result,
        )

    def tools_node(state: AgentState) -> AgentState:
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

        return AgentState(
            messages=msgs,
            user=state.user,
            cv_context=state.cv_context,
            plan=state.plan,
            pending_tools=state.pending_tools,
            last_control_op=state.last_control_op,
            last_control_mode=state.last_control_mode,
            last_control_result=state.last_control_result,
        )

    def route_after_agent(state: AgentState) -> str:
        """根据 agent 输出决定下一步走 tools 还是结束。"""

        msgs: List[BaseMessage] = list(state.messages)
        if not msgs:
            return END
        last = msgs[-1]
        tool_calls = getattr(last, "tool_calls", None) or []
        if tool_calls:
            return "tools"
        return END

    graph.add_node("agent", agent_node)
    graph.add_node("tools", tools_node)
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route_after_agent, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")

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
