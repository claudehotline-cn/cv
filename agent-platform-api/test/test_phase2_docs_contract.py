from pathlib import Path


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_production_readiness_includes_phase2_runbook_contract() -> None:
    content = (_repo_root() / "docs/production_readiness.md").read_text(encoding="utf-8")

    expected_contract_snippets = [
        "## 5. Phase2 运维 Runbook",
        "OTEL_ENABLED",
        "GET /cache/me/stats",
        "POST /admin/tenants/{tenant_id}/cache/invalidate",
        "GET /guardrails/me",
    ]

    for snippet in expected_contract_snippets:
        assert snippet in content, f"missing docs contract snippet: {snippet}"
