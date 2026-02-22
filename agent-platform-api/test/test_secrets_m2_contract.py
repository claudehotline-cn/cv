from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_mysql_repository_is_not_placeholder() -> None:
    src = (_repo_root() / "agent-platform-api/app/services/secrets_repository_mysql.py").read_text(encoding="utf-8")
    assert "class MySQLSecretRepository" in src
    assert "Placeholder" not in src
    assert "pymysql.connect" in src
    assert "CREATE TABLE IF NOT EXISTS secrets" in src
    assert "CREATE TABLE IF NOT EXISTS secret_versions" in src


def test_secrets_service_can_select_mysql_backend() -> None:
    src = (_repo_root() / "agent-platform-api/app/services/secrets_service.py").read_text(encoding="utf-8")
    assert "secrets_store_backend" in src
    assert 'if backend == "mysql"' in src
    assert "MySQLSecretRepository" in src
