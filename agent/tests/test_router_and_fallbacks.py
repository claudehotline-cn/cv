from __future__ import annotations

from typing import Any, Dict, List

import pytest
from langchain_core.messages import AIMessage

from cv_agent.server import api
from cv_agent.graph import control_plane as cp_mod


class _DummySettingsRouter:
    def __init__(self, provider: str = "openai", have_key: bool = True) -> None:
        self.llm_provider = provider
        self.openai_api_key = "dummy-key" if have_key else None
        self.llm_model = "dummy-model"
        # 其他字段在本测试中不会被使用


class _DummyLLM:
    """替代 ChatOpenAI/ChatOllama 的最小 LLM stub，只返回固定 AIMessage。"""

    def __init__(self, *args: Any, **kwargs: Any) -> None:  # type: ignore[override]
        pass

    def bind_tools(self, tools: List[Any]) -> "_DummyLLM":
        return self

    def invoke(self, messages: List[Any]) -> AIMessage:  # type: ignore[override]
        return AIMessage(content="dummy response")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "user_text,expected_task",
    [
        ("请帮我查看当前 pipeline 列表", "pipeline"),
        ("帮我看下最近的日志错误", "debug"),
        ("这个模型训练策略怎么优化", "model"),
    ],
)
async def test_router_sets_task_based_on_user_message(
    monkeypatch: pytest.MonkeyPatch,
    user_text: str,
    expected_task: str,
) -> None:
    """通过 _invoke_stategraph_agent 验证 Router 将不同输入路由到正确的 task。"""

    # 强制使用 openai + dummy key，避免走离线 fallback
    monkeypatch.setattr(api, "get_settings", lambda: _DummySettingsRouter(), raising=False)
    monkeypatch.setattr(cp_mod, "get_settings", lambda: _DummySettingsRouter(), raising=False)
    # 使用 Dummy LLM 替代 ChatOpenAI，避免真实网络调用
    monkeypatch.setattr(cp_mod, "ChatOpenAI", _DummyLLM, raising=False)

    user = api.UserContext(user_id="router-user", role="admin", tenant="tenant-router")
    msg = api.Message(role="user", content=user_text)

    state = await api._invoke_stategraph_agent(  # type: ignore[attr-defined]
        request_messages=[msg],
        user=user,
        thread_id="router-thread",
    )

    assert isinstance(state, dict)
    task = state.get("task")
    assert task == expected_task


class _DummyGraphInvalidHistory:
    def __init__(self) -> None:
        self.calls: List[Dict[str, Any]] = []

    async def ainvoke(self, state: Dict[str, Any], config: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        self.calls.append(config)
        if len(self.calls) == 1:
            # 模拟 LangGraph 抛出的 INVALID_CHAT_HISTORY 错误模式
            raise ValueError("Found AIMessages with tool_calls but no ToolMessages")
        # 第二次调用返回简单 state
        return {
            "messages": [
                ("assistant", "reset thread and continue"),
            ]
        }


@pytest.mark.asyncio
async def test_invoke_agent_graph_invalid_chat_history_recovers(monkeypatch: pytest.MonkeyPatch) -> None:
    """当 _invoke_agent_graph 遇到 INVALID_CHAT_HISTORY 时，应重建 thread_id 并成功返回结果。"""

    dummy_graph = _DummyGraphInvalidHistory()
    monkeypatch.setattr(api, "get_control_plane_agent", lambda: dummy_graph, raising=False)

    # provider=openai 且有 key，强制走正常 ReAct Agent 路径
    monkeypatch.setattr(api, "get_settings", lambda: _DummySettingsRouter(), raising=False)

    user = api.UserContext(user_id="hist-user", role="admin", tenant="hist-tenant")
    messages: List[tuple[str, str]] = [("user", "触发 INVALID_CHAT_HISTORY 的场景")]

    state = await api._invoke_agent_graph(  # type: ignore[attr-defined]
        messages=messages,
        user=user,
        thread_id="hist-thread",
    )

    assert isinstance(state, dict)
    msgs = state.get("messages", [])
    assert msgs, "INVALID_CHAT_HISTORY 重试后应返回至少一条消息"
    last = msgs[-1]
    if isinstance(last, tuple):
        _, content = last
    else:
        content = getattr(last, "content", str(last))
    assert "reset thread and continue" in str(content)
    # 验证 DummyGraph 被调用了两次：一次抛错，一次成功
    assert len(dummy_graph.calls) == 2
    first_tid = dummy_graph.calls[0]["configurable"]["thread_id"]
    second_tid = dummy_graph.calls[1]["configurable"]["thread_id"]
    assert first_tid != second_tid
    assert str(second_tid).startswith("reset-")


class _DummySettingsOffline(_DummySettingsRouter):
    def __init__(self) -> None:
        super().__init__(provider="openai", have_key=False)
        self.cp_base_url = "http://cp-spring:18080"


@pytest.mark.asyncio
async def test_invoke_agent_graph_offline_mode_without_openai_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """provider=openai 且未配置 OPENAI_API_KEY 时，应走离线模式并直接列出 pipelines。"""

    monkeypatch.setattr(api, "get_settings", lambda: _DummySettingsOffline(), raising=False)

    dummy_pipelines = [
        {"name": "p1", "graph_id": "g1", "default_model_id": "m1"},
        {"name": "p2", "graph_id": "g2", "default_model_id": "m2"},
    ]
    monkeypatch.setattr(api, "_fetch_pipelines", lambda limit=None, tenant=None: dummy_pipelines, raising=False)

    user = api.UserContext(user_id="offline-user", role="viewer", tenant="offline-tenant")
    messages: List[tuple[str, str]] = [("user", "列出所有 pipeline")]

    state = await api._invoke_agent_graph(  # type: ignore[attr-defined]
        messages=messages,
        user=user,
        thread_id="offline-thread",
    )

    assert isinstance(state, dict)
    assert state.get("offline") is True
    assert state.get("pipelines") == dummy_pipelines
    assert state.get("thread_id") == "offline-thread"
    msgs = state.get("messages", [])
    assert msgs and len(msgs) == 2
    _, assistant_content = msgs[-1]
    assert "本地测试模式" in assistant_content
    assert "p1" in assistant_content

