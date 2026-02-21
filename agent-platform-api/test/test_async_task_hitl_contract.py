import ast
from pathlib import Path

import pytest


@pytest.mark.unit
def test_list_session_tasks_active_includes_waiting_approval() -> None:
    """Regression: returning to a session must show HITL-paused async jobs as 'active'."""
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "agent-platform-api/app/routes/tasks.py"
    tree = ast.parse(src_path.read_text(encoding="utf-8"), filename=str(src_path))

    fn = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_session_tasks":
            fn = node
            break
    assert fn is not None, "list_session_tasks() not found"

    # Find the tuple/list literal used for the 'active' status filter.
    statuses = None
    for node in ast.walk(fn):
        if not isinstance(node, ast.Compare):
            continue
        if not (isinstance(node.left, ast.Name) and node.left.id == "status"):
            continue
        if not node.comparators:
            continue
        comp = node.comparators[0]
        if not (isinstance(comp, ast.Constant) and comp.value == "active"):
            continue

        # Look for the subsequent "t.status in (...)" container.
        parent = node
        # Walk the function again to find the first `In` comparison against t.status.
        for inner in ast.walk(fn):
            if not isinstance(inner, ast.Compare):
                continue
            if not (
                isinstance(inner.left, ast.Attribute)
                and inner.left.attr == "status"
                and isinstance(inner.left.value, ast.Name)
                and inner.left.value.id == "t"
            ):
                continue
            if not inner.ops or not isinstance(inner.ops[0], ast.In):
                continue
            container = inner.comparators[0] if inner.comparators else None
            if isinstance(container, (ast.Tuple, ast.List)):
                vals = []
                for elt in container.elts:
                    if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                        vals.append(elt.value)
                if vals:
                    statuses = vals
                    break
        break

    assert statuses is not None, "active task status filter not found"
    assert "waiting_approval" in statuses


@pytest.mark.unit
def test_worker_emits_task_waiting_approval_event() -> None:
    """Regression: worker must notify frontend when a job pauses for HITL."""
    repo_root = Path(__file__).resolve().parents[2]
    src_path = repo_root / "agent-platform-api/app/worker.py"
    text = src_path.read_text(encoding="utf-8")
    assert "task_waiting_approval" in text
