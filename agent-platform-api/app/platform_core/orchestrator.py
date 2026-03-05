import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping
from typing import Literal, Protocol, TypeAlias, cast

from app.platform_core.models import SemanticCacheKey, SemanticCacheValue

Payload: TypeAlias = dict[str, object]
ExecuteResult: TypeAlias = dict[str, object]
DecisionAction: TypeAlias = Literal["allow", "block", "redact"]


class RequestLike(Protocol):
    tenant_id: str | None
    namespace: str
    model_key: str
    query_text: str


class SpanLike(Protocol):
    def __enter__(self) -> object: ...

    def __exit__(self, _exc_type: object, _exc: object, _tb: object) -> bool | None: ...


class TelemetryLike(Protocol):
    def start_span(self, name: str, attributes: Mapping[str, str] | None = None) -> SpanLike: ...

    def increment(self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None) -> None: ...


class SemanticCacheLike(Protocol):
    async def lookup(self, key: SemanticCacheKey) -> SemanticCacheValue | None: ...

    async def store(self, key: SemanticCacheKey, value: SemanticCacheValue) -> None: ...


class PolicyDecisionLike(Protocol):
    action: DecisionAction
    reason_code: str | None
    payload: Mapping[str, object] | None
    sanitized_payload: Mapping[str, object] | None


PreInputCheck: TypeAlias = Callable[[RequestLike, "ExecuteContext"], Awaitable[PolicyDecisionLike]]
PostOutputCheck: TypeAlias = Callable[[RequestLike, Payload, "ExecuteContext"], Awaitable[PolicyDecisionLike]]
Executor: TypeAlias = Callable[["ExecuteContext"], Awaitable[Payload]]


class ExecuteContext(Protocol):
    telemetry: TelemetryLike
    semantic_cache: SemanticCacheLike
    pre_input_check: PreInputCheck | None
    post_output_check: PostOutputCheck | None
    cacheable: bool | None


def _cache_key(request: RequestLike) -> SemanticCacheKey:
    model_key = str(getattr(request, "model_key", ""))
    query_text = str(getattr(request, "query_text", ""))
    prompt_hash = hashlib.sha256(f"{model_key}\n{query_text}".encode("utf-8")).hexdigest()
    return SemanticCacheKey(
        prompt_hash=prompt_hash,
        tenant_id=cast(str | None, getattr(request, "tenant_id", None)),
        namespace=str(getattr(request, "namespace", "default")),
    )


async def execute(
    request: RequestLike,
    ctx: ExecuteContext,
    executor: Executor,
) -> ExecuteResult:
    tenant_id = request.tenant_id
    telemetry = ctx.telemetry

    span_attributes = {
        "tenant_id": str(tenant_id),
        "namespace": str(request.namespace),
        "model_key": str(request.model_key),
    }

    with telemetry.start_span("agent.run", attributes=span_attributes):
        pre_input_check = ctx.pre_input_check
        if pre_input_check is not None:
            decision = await pre_input_check(request, ctx)
            if decision.action == "block":
                telemetry.increment(
                    "agent.policy.blocked",
                    attributes={
                        **span_attributes,
                        "stage": "input",
                        "reason_code": str(decision.reason_code),
                    },
                )
                blocked_payload = decision.payload
                if blocked_payload is None:
                    blocked_payload = {"blocked": True}
                return {
                    "status": "blocked",
                    "reason_code": decision.reason_code,
                    "payload": blocked_payload,
                }

        cache = ctx.semantic_cache
        key = _cache_key(request)
        cached = await cache.lookup(key)
        if cached is not None and cached.response:
            payload = cast(Payload, json.loads(cached.response))
            telemetry.increment(
                "agent.cache.hit",
                attributes={
                    "tenant_id": str(tenant_id),
                    "namespace": str(request.namespace),
                    "model_key": str(request.model_key),
                },
            )
            return {
                "status": "ok",
                "reason_code": "cache_hit",
                "payload": payload,
            }

        payload = await executor(ctx)
        decision: PolicyDecisionLike | None = None
        post_output_check = ctx.post_output_check
        if post_output_check is not None:
            decision = await post_output_check(request, payload, ctx)
            if decision.action == "block":
                telemetry.increment(
                    "agent.policy.blocked",
                    attributes={
                        **span_attributes,
                        "stage": "output",
                        "reason_code": str(decision.reason_code),
                    },
                )
                blocked_payload = decision.payload
                if blocked_payload is None:
                    blocked_payload = {"blocked": True}
                return {
                    "status": "blocked",
                    "reason_code": decision.reason_code,
                    "payload": blocked_payload,
                }
            sanitized_payload = decision.sanitized_payload
            if sanitized_payload is not None:
                payload = cast(Payload, sanitized_payload)

        action: DecisionAction = decision.action if decision is not None else "allow"
        if action in ("allow", "redact") and ctx.cacheable is not False:
            await cache.store(
                key,
                SemanticCacheValue(
                    response=json.dumps(payload),
                    metadata={},
                ),
            )

        reason_code = decision.reason_code if decision is not None else None
        return {
            "status": "ok",
            "reason_code": reason_code,
            "payload": payload,
        }
