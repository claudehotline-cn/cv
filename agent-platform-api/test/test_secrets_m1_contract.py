import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_secrets_ports_and_repositories_exist() -> None:
    repo = _repo_root()
    assert (repo / "agent-platform-api/app/ports/secrets.py").exists()
    assert (repo / "agent-platform-api/app/services/secrets_repository_pg.py").exists()
    assert (repo / "agent-platform-api/app/services/secrets_repository_mysql.py").exists()
    assert (repo / "agent-platform-api/app/services/secrets_injector.py").exists()


def test_secrets_router_has_admin_tenant_endpoints() -> None:
    src = (_repo_root() / "agent-platform-api/app/routes/secrets.py").read_text(encoding="utf-8")
    assert '@router.get("/admin/tenants/{tenant_id}")' in src
    assert '@router.post("/admin/tenants/{tenant_id}")' in src


def test_tasks_supports_secret_refs_and_injector() -> None:
    src = (_repo_root() / "agent-platform-api/app/routes/tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    execute_fn = None
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == "ExecuteRequest":
            execute_fn = node
            break
    assert execute_fn is not None
    execute_src = ast.get_source_segment(src, execute_fn) or ""
    assert "secret_refs" in execute_src
    assert "RuntimeSecretInjector" in src


def test_secrets_tables_defined_in_models_and_migration() -> None:
    models_src = (_repo_root() / "agent-platform-api/app/models/db_models.py").read_text(encoding="utf-8")
    db_src = (_repo_root() / "agent-platform-api/app/db.py").read_text(encoding="utf-8")
    assert "class SecretModel" in models_src
    assert "class SecretVersionModel" in models_src
    assert "CREATE TABLE IF NOT EXISTS secrets" in db_src
    assert "CREATE TABLE IF NOT EXISTS secret_versions" in db_src


def test_audit_has_secret_redaction_hook() -> None:
    src = (_repo_root() / "agent-platform-api/app/services/audit_service.py").read_text(encoding="utf-8")
    assert "redact_payload" in src
