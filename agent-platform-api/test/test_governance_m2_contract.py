import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_limits_route_registered_in_main() -> None:
    src_path = _repo_root() / "agent-platform-api/app/main.py"
    src = src_path.read_text(encoding="utf-8")
    tree = ast.parse(src)

    assert "from app.routes import" in src
    assert "limits" in src
    assert "app.include_router(limits.router)" in src

    imports = [n for n in tree.body if isinstance(n, ast.ImportFrom)]
    assert any(i.module == "app.routes" for i in imports)


def test_limits_routes_and_quota_service_exist() -> None:
    repo = _repo_root()
    limits_path = repo / "agent-platform-api/app/routes/limits.py"
    quota_path = repo / "agent-platform-api/app/services/quota_service.py"

    limits_src = limits_path.read_text(encoding="utf-8")
    quota_src = quota_path.read_text(encoding="utf-8")

    for route in (
        "/me",
        "/quota/me",
        "/admin/tenants/{tenant_id}",
        "/admin/tenants/{tenant_id}/quota",
    ):
        assert route in limits_src

    assert "@router.put(\"/admin/tenants/{tenant_id}\")" in limits_src
    assert "@router.put(\"/admin/tenants/{tenant_id}/quota\")" in limits_src
    assert "@quota_router.get(\"/me\")" in limits_src

    for fn in ("ensure_defaults", "get_limits", "get_quota", "check_quota_or_raise", "consume_tokens"):
        assert f"def {fn}" in quota_src or f"async def {fn}" in quota_src

    for fn in ("update_limits", "update_quota"):
        assert f"def {fn}" in quota_src or f"async def {fn}" in quota_src


def test_tasks_and_audit_hook_quota_flow() -> None:
    repo = _repo_root()
    tasks_src = (repo / "agent-platform-api/app/routes/tasks.py").read_text(encoding="utf-8")
    audit_src = (repo / "agent-platform-api/app/services/audit_service.py").read_text(encoding="utf-8")

    assert "check_quota_or_raise" in tasks_src
    assert "consume_tokens" in audit_src

    sessions_src = (repo / "agent-platform-api/app/routes/sessions.py").read_text(encoding="utf-8")
    assert "get_effective_rw_policy" in sessions_src
    assert "enforce_rate_limit" in sessions_src


def test_rag_governance_hooks_present() -> None:
    rag_src = (_repo_root() / "agent-platform-api/app/routes/rag.py").read_text(encoding="utf-8")
    assert "_require_rag_governance" in rag_src
    assert "enforce_rate_limit" in rag_src
    assert "check_quota_or_raise" in rag_src
