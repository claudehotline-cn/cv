from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_rag_proxy_supports_secret_refs_injection() -> None:
    src = (_repo_root() / "agent-platform-api/app/routes/rag.py").read_text(encoding="utf-8")
    assert "secret_refs" in src
    assert "RuntimeSecretInjector" in src
    assert "SecretsService" in src
    assert "inject(runtime_config=body, resolved=resolved)" in src
