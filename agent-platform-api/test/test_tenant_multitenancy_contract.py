import ast
from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _class_node(tree: ast.Module, class_name: str) -> ast.ClassDef:
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return node
    raise AssertionError(f"class {class_name} not found")


def _class_has_tenant_column_non_nullable(cls: ast.ClassDef) -> bool:
    for node in cls.body:
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != "tenant_id":
            continue
        call = node.value
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Name) or call.func.id != "mapped_column":
            continue
        for kw in call.keywords:
            if kw.arg == "nullable" and isinstance(kw.value, ast.Constant) and kw.value.value is False:
                return True
    return False


def test_models_require_tenant_id_on_core_tables() -> None:
    src = _repo_root() / "agent-platform-api/app/models/db_models.py"
    tree = ast.parse(src.read_text(encoding="utf-8"), filename=str(src))

    for class_name in ("SessionModel", "TaskModel", "AgentRunModel", "AuditEventModel", "AuthAuditEventModel"):
        cls = _class_node(tree, class_name)
        assert _class_has_tenant_column_non_nullable(cls), f"{class_name}.tenant_id must be nullable=False"


def test_init_db_migrates_and_enforces_tenant_columns() -> None:
    src = _repo_root() / "agent-platform-api/app/db.py"
    text = src.read_text(encoding="utf-8")

    required_add = (
        "ALTER TABLE agent_runs ADD COLUMN IF NOT EXISTS tenant_id UUID",
        "ALTER TABLE audit_events ADD COLUMN IF NOT EXISTS tenant_id UUID",
        "ALTER TABLE auth_audit_events ADD COLUMN IF NOT EXISTS tenant_id UUID",
    )
    required_not_null = (
        "ALTER TABLE agent_runs ALTER COLUMN tenant_id SET NOT NULL",
        "ALTER TABLE audit_events ALTER COLUMN tenant_id SET NOT NULL",
        "ALTER TABLE auth_audit_events ALTER COLUMN tenant_id SET NOT NULL",
    )

    for sql in (*required_add, *required_not_null):
        assert sql in text


def test_frontend_has_tenant_switcher_contract() -> None:
    repo = _repo_root()
    api_client = (repo / "agent-chat-vue/src/api/client.ts").read_text(encoding="utf-8")
    auth_store = (repo / "agent-chat-vue/src/stores/auth.ts").read_text(encoding="utf-8")
    sidebar = (repo / "agent-chat-vue/src/components/layout/AppSidebar.vue").read_text(encoding="utf-8")

    assert "X-Tenant-Id" in api_client
    assert "switchTenant" in auth_store
    assert "tenant-switcher" in sidebar
