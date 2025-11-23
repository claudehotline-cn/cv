from typing import Any, List, Tuple

from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from ..config import get_settings
from ..store import get_checkpointer
from ..tools import get_all_tools

_CONTROL_PLANE_AGENT: Any | None = None


def _build_agent() -> Any:
    """Construct the ReAct-style control-plane agent graph."""

    settings = get_settings()
    model = ChatOpenAI(model=settings.llm_model, api_key=settings.openai_api_key)
    tools = get_all_tools()
    checkpointer = get_checkpointer()
    agent_graph = create_react_agent(
        model=model,
        tools=tools,
        checkpointer=checkpointer,
    )
    return agent_graph


def get_control_plane_agent() -> Any:
    """Return a singleton control-plane agent graph instance."""

    global _CONTROL_PLANE_AGENT
    if _CONTROL_PLANE_AGENT is None:
        _CONTROL_PLANE_AGENT = _build_agent()
    return _CONTROL_PLANE_AGENT


def build_state_from_tuples(
    messages: List[Tuple[str, str]],
) -> dict:
    """
    Build LangGraph state dict from (role, content) tuples.

    LangGraph 的 ReAct 预构建 Agent 接受形如：
        { "messages": [("user", "…"), ("assistant", "…")] }
    的输入。
    """

    return {"messages": messages}
