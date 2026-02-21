import ast
from pathlib import Path
from typing import TypedDict

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

# Import fixture to make it available to pytest (agent-test framework)
from agent_test.fixtures import memory_saver  # noqa: F401


def test_resume_route_uses_session_thread_id() -> None:
    """Regression test: /sessions/{session_id}/resume must use session.thread_id.

    If resume uses session.id as thread_id, LangGraph will not resume the interrupted run.
    """
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "agent-platform-api/app/routes/chat.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    resume_fn = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "resume_chat":
            resume_fn = node
            break
    assert resume_fn is not None, "resume_chat() not found"

    thread_assign = None
    for node in resume_fn.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "thread_id":
                thread_assign = node
                break
    assert thread_assign is not None, "resume_chat() must assign a local 'thread_id' variable"

    # Expect: thread_id = str(session.thread_id) if session.thread_id else str(session.id)
    assert isinstance(thread_assign.value, ast.IfExp), "thread_id assignment must be conditional on session.thread_id"
    ifexp = thread_assign.value

    assert isinstance(ifexp.test, ast.Attribute)
    assert isinstance(ifexp.test.value, ast.Name) and ifexp.test.value.id == "session"
    assert ifexp.test.attr == "thread_id"

    assert isinstance(ifexp.body, ast.Call)
    assert isinstance(ifexp.body.func, ast.Name) and ifexp.body.func.id == "str"
    assert len(ifexp.body.args) == 1
    assert isinstance(ifexp.body.args[0], ast.Attribute)
    assert isinstance(ifexp.body.args[0].value, ast.Name) and ifexp.body.args[0].value.id == "session"
    assert ifexp.body.args[0].attr == "thread_id"

    assert isinstance(ifexp.orelse, ast.Call)
    assert isinstance(ifexp.orelse.func, ast.Name) and ifexp.orelse.func.id == "str"
    assert len(ifexp.orelse.args) == 1
    assert isinstance(ifexp.orelse.args[0], ast.Attribute)
    assert isinstance(ifexp.orelse.args[0].value, ast.Name) and ifexp.orelse.args[0].value.id == "session"
    assert ifexp.orelse.args[0].attr == "id"


class _State(TypedDict):
    x: int
    approved: bool


def _interrupt_node(_: _State):
    decision = interrupt({"question": "approve?"})
    approved = bool(isinstance(decision, list) and decision and decision[0].get("type") == "approve")
    return {"approved": approved}


@pytest.mark.unit
def test_langgraph_resume_requires_same_thread_id(memory_saver: InMemorySaver) -> None:
    """Demonstrate why resume thread_id must match the original thread_id."""
    builder = StateGraph(_State)
    builder.add_node("n", _interrupt_node)
    builder.add_edge(START, "n")
    builder.add_edge("n", END)
    graph = builder.compile(checkpointer=memory_saver)

    config_a = {"configurable": {"thread_id": "thread-a"}}
    config_b = {"configurable": {"thread_id": "thread-b"}}

    out = graph.invoke({"x": 1}, config_a)
    assert "__interrupt__" in out

    # Wrong thread_id: does NOT resume the interrupted run; it starts a new run that interrupts again.
    out_wrong = graph.invoke(Command(resume=[{"type": "approve", "message": "ok"}]), config_b)
    assert "__interrupt__" in out_wrong
    assert graph.get_state(config_a).values == {"x": 1}

    # Correct thread_id: resumes and completes.
    out_ok = graph.invoke(Command(resume=[{"type": "approve", "message": "ok"}]), config_a)
    assert out_ok.get("approved") is True
