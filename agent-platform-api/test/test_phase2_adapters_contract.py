from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest


class _FakeResult:
    def __init__(self, row: dict[str, Any] | None = None) -> None:
        self._row = row

    def mappings(self) -> "_FakeResult":
        return self

    def first(self) -> dict[str, Any] | None:
        return self._row


class _FakeSession:
    def __init__(
        self,
        *,
        policy_row: dict[str, Any] | None = None,
        exact_lookup_row: dict[str, Any] | None = None,
        vector_lookup_row: dict[str, Any] | None = None,
    ) -> None:
        self.policy_row = policy_row
        self.exact_lookup_row = exact_lookup_row
        self.vector_lookup_row = vector_lookup_row
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def execute(self, statement: Any, params: dict[str, Any] | None = None) -> _FakeResult:
        sql = str(statement)
        bound = dict(params or {})
        self.calls.append((sql, bound))

        if "FROM tenant_guardrail_policies" in sql:
            return _FakeResult(self.policy_row)

        if "FROM semantic_cache_entries" in sql and "ORDER BY embedding <=>" in sql:
            if self.vector_lookup_row is None:
                return _FakeResult(None)
            row = dict(self.vector_lookup_row)
            row.setdefault("id", "cache-semantic-1")
            return _FakeResult(row)

        if "FROM semantic_cache_entries" in sql and "prompt_hash =" in sql:
            if bound.get("prompt_hash") == "abc123" and self.exact_lookup_row is not None:
                row = dict(self.exact_lookup_row)
                row.setdefault("id", "cache-exact-1")
                return _FakeResult(row)
            return _FakeResult(None)

        return _FakeResult(None)


class _FakeSessionContext:
    def __init__(self, session: _FakeSession) -> None:
        self._session = session

    async def __aenter__(self) -> _FakeSession:
        return self._session

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        _ = (exc_type, exc, tb)
        return False


@dataclass(frozen=True)
class _RichSemanticCacheKey:
    prompt_hash: str
    tenant_id: str | None
    namespace: str
    model_key: str
    embedding: list[float] | None = None


def _factory_for(session: _FakeSession):
    return lambda: _FakeSessionContext(session)


def _load_agent_core_attr(module_name: str, attr_name: str):
    import importlib
    import sys
    from pathlib import Path

    worktree_root = Path(__file__).resolve().parents[2]
    agent_core_path = str(worktree_root / "agent-core")
    if agent_core_path not in sys.path:
        sys.path.insert(0, agent_core_path)

    module = importlib.import_module(module_name)
    return getattr(module, attr_name)


def test_adapters_are_importable_and_match_ports() -> None:
    from app.adapters.cache_pgvector import PgVectorSemanticCacheAdapter
    from app.adapters.guardrails_db import DbGuardrailAdapter
    from app.adapters.telemetry_otel import OTelTelemetryAdapter

    guardrails_port = _load_agent_core_attr("app.platform_core.contracts.guardrails", "GuardrailsPort")
    semantic_cache_port = _load_agent_core_attr("app.platform_core.contracts.semantic_cache", "SemanticCachePort")
    telemetry_port = _load_agent_core_attr("app.platform_core.contracts.telemetry", "TelemetryPort")

    guardrails = DbGuardrailAdapter(session_factory=_factory_for(_FakeSession()))
    cache = PgVectorSemanticCacheAdapter(session_factory=_factory_for(_FakeSession()))
    telemetry = OTelTelemetryAdapter(enabled=False)

    assert isinstance(guardrails, guardrails_port)
    assert isinstance(cache, semantic_cache_port)
    assert isinstance(telemetry, telemetry_port)


@pytest.mark.asyncio
async def test_db_guardrail_adapter_evaluates_and_persists_actions() -> None:
    from app.adapters.guardrails_db import DbGuardrailAdapter

    session = _FakeSession(
        policy_row={
            "enabled": True,
            "mode": "enforce",
            "config": {
                "input_block_keywords": ["drop table"],
                "output_approval_keywords": ["wire transfer"],
                "output_redact_keywords": ["secret"],
                "detect_pii": True,
            },
        }
    )
    adapter = DbGuardrailAdapter(session_factory=_factory_for(session))

    blocked = await adapter.evaluate_input(
        tenant_id="00000000-0000-0000-0000-000000000001",
        text="please DROP TABLE users",
        request_id="11111111-1111-1111-1111-111111111111",
    )
    redacted = await adapter.evaluate_output(
        tenant_id="00000000-0000-0000-0000-000000000001",
        text="reach me at alice@example.com",
        request_id="11111111-1111-1111-1111-111111111111",
    )
    approval = await adapter.evaluate_output(
        tenant_id="00000000-0000-0000-0000-000000000001",
        text="please wire transfer this invoice",
        request_id="11111111-1111-1111-1111-111111111111",
    )

    assert blocked.action == "block"
    assert redacted.action == "redact"
    assert approval.action == "require_approval"

    inserts = [params for (sql, params) in session.calls if "INSERT INTO guardrail_events" in sql]
    assert [item.get("action") for item in inserts] == ["block", "redact", "require_approval"]


@pytest.mark.asyncio
async def test_pgvector_semantic_cache_lookup_store_and_vector_fallback() -> None:
    from app.adapters.cache_pgvector import PgVectorSemanticCacheAdapter
    from app.platform_core.models import SemanticCacheKey, SemanticCacheValue

    session = _FakeSession(
        exact_lookup_row={
            "response": '{"answer":"cached"}',
            "metadata": {"model_key": "gpt-4o", "hit_count": 3},
        },
        vector_lookup_row={
            "response": '{"answer":"semantic"}',
            "metadata": {"model_key": "gpt-4o-mini", "hit_count": 1},
        },
    )

    adapter = PgVectorSemanticCacheAdapter(
        session_factory=_factory_for(session),
        ttl_seconds=3600,
        similarity_threshold=0.4,
    )

    exact_key = SemanticCacheKey(prompt_hash="abc123", tenant_id="tenant-1", namespace="chat")
    exact_value = await adapter.lookup(exact_key)
    assert exact_value is not None
    assert exact_value.response == '{"answer":"cached"}'

    await adapter.store(
        exact_key,
        SemanticCacheValue(response='{"answer":"fresh"}', metadata={"model_key": "gpt-4o"}),
    )

    semantic_key = _RichSemanticCacheKey(
        prompt_hash="does-not-hit-exact",
        tenant_id="tenant-1",
        namespace="chat",
        model_key="gpt-4o-mini",
        embedding=[0.11, 0.22],
    )
    semantic_value = await adapter.lookup(semantic_key)  # type: ignore[arg-type]
    assert semantic_value is not None
    assert semantic_value.response == '{"answer":"semantic"}'

    sql_calls = [sql for (sql, _) in session.calls]
    assert any("ORDER BY embedding <=>" in sql for sql in sql_calls)
    assert any("INSERT INTO semantic_cache_entries" in sql for sql in sql_calls)
    assert any("jsonb_set" in sql and "hit_count" in sql for sql in sql_calls)


def test_otel_adapter_and_observability_noop_surface() -> None:
    from app.adapters.telemetry_otel import OTelTelemetryAdapter

    settings = _load_agent_core_attr("agent_core.settings", "Settings")()
    noop_span = _load_agent_core_attr("agent_core.observability", "NoopSpan")

    assert hasattr(settings, "otel_enabled")
    assert hasattr(settings, "otel_exporter_otlp_endpoint")
    assert hasattr(settings, "otel_service_name")
    assert hasattr(settings, "otel_sample_rate")
    assert hasattr(settings, "otel_fail_mode")
    assert hasattr(settings, "semantic_cache_enabled")
    assert hasattr(settings, "semantic_cache_similarity_threshold")
    assert hasattr(settings, "semantic_cache_ttl_seconds")

    telemetry = OTelTelemetryAdapter(enabled=False)
    with telemetry.start_span("phase2.test", attributes={"tenant_id": "t-1"}):
        telemetry.increment("phase2.metric", attributes={"k": "v"})
        telemetry.counter("phase2.counter", 2, attributes={"k": "v"})
        telemetry.record_latency_ms("phase2.latency", 12.0, attributes={"k": "v"})
        telemetry.histogram("phase2.histogram", 12.0, attributes={"k": "v"})

    with noop_span():
        pass
