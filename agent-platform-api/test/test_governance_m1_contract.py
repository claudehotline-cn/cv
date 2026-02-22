import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_governance_module_files_exist() -> None:
    repo = _repo_root()
    assert (repo / "agent-platform-api/app/core/rate_limit.py").exists()
    assert (repo / "agent-platform-api/app/core/concurrency_limit.py").exists()
    assert (repo / "agent-platform-api/app/core/governance.py").exists()


def test_tasks_execute_enqueues_tenant_id_and_governance_checks() -> None:
    src = (_repo_root() / "agent-platform-api/app/routes/tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    fn = None
    for node in tree.body:
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "create_execute_task":
            fn = node
            break
    assert fn is not None

    text = ast.get_source_segment(src, fn) or ""
    assert "enforce_rate_limit(" in text
    assert "\"execute\"" in text
    assert "acquire_execute_concurrency(" in text
    assert "release_execute_concurrency(governance_keys)" in text
    assert "tenant_id_str" in text


def test_worker_execute_resume_accept_tenant_id_and_release_concurrency() -> None:
    src = (_repo_root() / "agent-platform-api/app/worker.py").read_text(encoding="utf-8")
    tree = ast.parse(src)

    names = {n.name: n for n in tree.body if isinstance(n, ast.AsyncFunctionDef)}
    exec_fn = names.get("agent_execute_task")
    resume_fn = names.get("agent_resume_task")
    assert exec_fn is not None
    assert resume_fn is not None

    exec_src = ast.get_source_segment(src, exec_fn) or ""
    resume_src = ast.get_source_segment(src, resume_fn) or ""

    assert "tenant_id: str" in exec_src
    assert "tenant_id: str" in resume_src
    assert "release_execute_concurrency" in exec_src
    assert "release_execute_concurrency" in resume_src
