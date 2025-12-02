from __future__ import annotations

from typing import Any, Dict, List

import pytest
from langgraph.errors import GraphRecursionError

from cv_agent.server import api


class _DummyGraph:
    async def ainvoke(self, state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        raise GraphRecursionError("recursion limit reached in dummy graph")


@pytest.mark.asyncio
async def test_invoke_stategraph_agent_recursion_error_returns_friendly_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """当 StateGraph 触发 GraphRecursionError 时，应返回友好的提示消息而非抛出异常。"""

    monkeypatch.setattr(api, "get_stategraph_agent", lambda: _DummyGraph())

    user = api.UserContext(user_id="u-rec", role="admin", tenant="t-rec")
    msg = api.Message(role="user", content="请帮我一直循环调用工具直到崩溃")

    state = await api._invoke_stategraph_agent(  # type: ignore[attr-defined]
        request_messages=[msg],
        user=user,
        thread_id="thread-recursion-test",
    )

    assert isinstance(state, dict)
    messages: List[Any] = state.get("messages", [])
    assert messages, "state.messages 应至少包含一条 AI 错误提示消息"
    last = messages[-1]
    content = getattr(last, "content", str(last))
    assert "超过上限" in str(content)

