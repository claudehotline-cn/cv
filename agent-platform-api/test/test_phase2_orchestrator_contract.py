import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol, TypeAlias

import pytest

from app.platform_core.models import SemanticCacheValue
from app.platform_core.orchestrator import execute
from app.platform_core.policy import PolicyDecision

Payload: TypeAlias = Mapping[str, object]

ExecuteFn: TypeAlias = Callable[
    [Any, Any, Callable[[Any], Awaitable[Payload]]],
    Awaitable[Payload],
]


class _NoopSpan:
    def __enter__(self):
        return self

    def __exit__(self, _exc_type, _exc, _tb):
        _ = (_exc_type, _exc, _tb)
        return False


class FakeTelemetry:
    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []
        self.increments: list[tuple[str, int, dict[str, str] | None]] = []

    def start_span(self, name: str, attributes: dict[str, str] | None = None):
        self.spans.append((name, dict(attributes or {})))
        return _NoopSpan()

    def increment(self, name: str, value: int = 1, attributes: dict[str, str] | None = None) -> None:
        self.increments.append((name, value, attributes))

    def record_latency_ms(self, name: str, value_ms: float, attributes: dict[str, str] | None = None) -> None:
        _ = (name, value_ms, attributes)


class _CacheKeyLike(Protocol):
    tenant_id: str | None
    namespace: str
    prompt_hash: str


class _CacheValueLike(Protocol):
    @property
    def response(self) -> str: ...


class FakeCache:
    def __init__(self, value: _CacheValueLike | None = None) -> None:
        self.value = value
        self.lookup_keys: list[_CacheKeyLike] = []
        self.stores: list[tuple[_CacheKeyLike, _CacheValueLike]] = []

    async def lookup(self, key: _CacheKeyLike) -> _CacheValueLike | None:
        self.lookup_keys.append(key)
        return self.value

    async def store(self, key: _CacheKeyLike, value: _CacheValueLike) -> None:
        self.stores.append((key, value))


@dataclass
class Request:
    tenant_id: str | None
    namespace: str
    model_key: str
    query_text: str


@dataclass
class Ctx:
    telemetry: Any
    semantic_cache: Any
    cacheable: bool | None = None
    pre_input_check: Any = None
    post_output_check: Any = None


@pytest.mark.asyncio
async def test_execute_starts_span_and_blocks_on_pre_input_check() -> None:
    telemetry = FakeTelemetry()
    cache = FakeCache()

    async def pre_check(request, ctx):
        _ = (request, ctx)
        return PolicyDecision(action="block", reason_code="policy_input_block", payload={"blocked": True})

    ctx = Ctx(telemetry=telemetry, semantic_cache=cache, pre_input_check=pre_check)
    request = Request(tenant_id="t-1", namespace="n-1", model_key="gpt-4", query_text="unsafe")

    called = {"executor": 0}

    async def executor(inner_ctx: Any) -> dict[str, object]:
        _ = inner_ctx
        called["executor"] += 1
        return {"answer": "should-not-run"}

    result = await execute(request, ctx, executor)

    assert telemetry.spans == [
        (
            "agent.run",
            {
                "tenant_id": "t-1",
                "namespace": "n-1",
                "model_key": "gpt-4",
            },
        )
    ]
    assert telemetry.increments == [
        (
            "agent.policy.blocked",
            1,
            {
                "tenant_id": "t-1",
                "namespace": "n-1",
                "model_key": "gpt-4",
                "stage": "input",
                "reason_code": "policy_input_block",
            },
        )
    ]
    assert called["executor"] == 0
    assert cache.lookup_keys == []
    assert result == {
        "status": "blocked",
        "reason_code": "policy_input_block",
        "payload": {"blocked": True},
    }


@pytest.mark.asyncio
async def test_execute_returns_cached_payload_and_increments_counter() -> None:
    telemetry = FakeTelemetry()
    cached_payload = {"answer": "from-cache"}
    cache = FakeCache(value=SemanticCacheValue(response=json.dumps(cached_payload), metadata={}))
    ctx = Ctx(telemetry=telemetry, semantic_cache=cache)
    request = Request(tenant_id="tenant-a", namespace="chat", model_key="model-x", query_text="hello")

    called = {"executor": 0}

    async def executor(inner_ctx: Any) -> dict[str, object]:
        _ = inner_ctx
        called["executor"] += 1
        return {"answer": "from-executor"}

    result = await execute(request, ctx, executor)

    expected_hash = hashlib.sha256("model-x\nhello".encode("utf-8")).hexdigest()
    assert cache.lookup_keys[0].tenant_id == "tenant-a"
    assert cache.lookup_keys[0].namespace == "chat"
    assert cache.lookup_keys[0].prompt_hash == expected_hash

    assert called["executor"] == 0
    assert telemetry.spans == [
        (
            "agent.run",
            {
                "tenant_id": "tenant-a",
                "namespace": "chat",
                "model_key": "model-x",
            },
        )
    ]
    assert telemetry.increments == [
        ("agent.cache.hit", 1, {"tenant_id": "tenant-a", "namespace": "chat", "model_key": "model-x"})
    ]
    assert result == {"status": "ok", "reason_code": "cache_hit", "payload": cached_payload}


@pytest.mark.asyncio
async def test_execute_miss_calls_executor_applies_sanitized_payload_and_writes_cache() -> None:
    telemetry = FakeTelemetry()
    cache = FakeCache(value=None)

    calls: dict[str, Any] = {"post_payload": None}

    async def post_check(request, payload, ctx):
        _ = (request, ctx)
        calls["post_payload"] = payload
        return PolicyDecision(
            action="redact",
            reason_code="policy_output_redact",
            sanitized_payload={"answer": "safe"},
        )

    ctx = Ctx(telemetry=telemetry, semantic_cache=cache, post_output_check=post_check)
    request = Request(tenant_id="tenant-b", namespace="chat", model_key="model-y", query_text="question")

    async def executor(inner_ctx: Any) -> dict[str, object]:
        _ = inner_ctx
        return {"answer": "raw"}

    result = await execute(request, ctx, executor)

    assert calls["post_payload"] == {"answer": "raw"}
    assert len(cache.stores) == 1
    stored_value = cache.stores[0][1]
    assert json.loads(stored_value.response) == {"answer": "safe"}
    assert result == {
        "status": "ok",
        "reason_code": "policy_output_redact",
        "payload": {"answer": "safe"},
    }


@pytest.mark.asyncio
async def test_execute_blocks_on_post_output_check_and_skips_cache_write() -> None:
    telemetry = FakeTelemetry()
    cache = FakeCache(value=None)

    async def post_check(request, payload, ctx):
        _ = (request, payload, ctx)
        return PolicyDecision(action="block", reason_code="policy_output_block", payload={"blocked": True})

    ctx = Ctx(telemetry=telemetry, semantic_cache=cache, post_output_check=post_check)
    request = Request(tenant_id="tenant-c", namespace="chat", model_key="model-z", query_text="question")

    async def executor(inner_ctx: Any) -> dict[str, object]:
        _ = inner_ctx
        return {"answer": "raw"}

    result = await execute(request, ctx, executor)

    assert telemetry.spans == [
        (
            "agent.run",
            {
                "tenant_id": "tenant-c",
                "namespace": "chat",
                "model_key": "model-z",
            },
        )
    ]
    assert telemetry.increments == [
        (
            "agent.policy.blocked",
            1,
            {
                "tenant_id": "tenant-c",
                "namespace": "chat",
                "model_key": "model-z",
                "stage": "output",
                "reason_code": "policy_output_block",
            },
        )
    ]
    assert cache.stores == []
    assert result == {
        "status": "blocked",
        "reason_code": "policy_output_block",
        "payload": {"blocked": True},
    }


@pytest.mark.asyncio
async def test_execute_does_not_write_cache_when_ctx_cacheable_is_false() -> None:
    telemetry = FakeTelemetry()
    cache = FakeCache(value=None)

    async def post_check(request, payload, ctx):
        _ = (request, payload, ctx)
        return PolicyDecision(action="allow", reason_code=None)

    ctx = Ctx(telemetry=telemetry, semantic_cache=cache, cacheable=False, post_output_check=post_check)
    request = Request(tenant_id="tenant-c", namespace="chat", model_key="model-z", query_text="question")

    async def executor(inner_ctx: Any) -> dict[str, object]:
        _ = inner_ctx
        return {"answer": "raw"}

    result = await execute(request, ctx, executor)

    assert cache.stores == []
    assert result == {"status": "ok", "reason_code": None, "payload": {"answer": "raw"}}
