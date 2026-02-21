import ast
from pathlib import Path

import pytest


@pytest.mark.unit
def test_async_task_uses_task_id_as_thread_id() -> None:
    """Regression test: async job must run on thread_id == task_id (not session.thread_id)."""
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "agent-platform-api/app/routes/tasks.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    fn = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_execute_task":
            fn = node
            break
    assert fn is not None, "create_execute_task() not found"

    enqueue_call = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Await):
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Attribute):
            continue
        if call.func.attr != "enqueue_job":
            continue
        if not call.args:
            continue
        first = call.args[0]
        if isinstance(first, ast.Constant) and first.value == "agent_execute_task":
            enqueue_call = call
            break

    assert enqueue_call is not None, "enqueue_job('agent_execute_task', ...) not found"
    assert enqueue_call.args, "enqueue_job must use positional args"

    # Last positional arg is thread_id.
    last_arg = enqueue_call.args[-1]
    assert isinstance(last_arg, ast.Name), "thread_id arg should be a local variable"
    assert last_arg.id == "task_thread_id"

