from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Protocol

from app.adapters.telemetry_otel import OTelTelemetryAdapter
from app.platform_core.orchestrator import (
    ExecuteContext,
    ExecuteResult,
    Executor,
    RequestLike,
    execute,
)

Orchestrator = Callable[[RequestLike, ExecuteContext, Executor], Awaitable[ExecuteResult]]


class GuardrailsAdapterLike(Protocol):
    async def evaluate_input(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> Any: ...

    async def evaluate_output(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> Any: ...


class SemanticCacheAdapterLike(Protocol):
    async def lookup(self, key: Any) -> Any: ...

    async def store(self, key: Any, value: Any) -> None: ...


class _LazyGuardrailsAdapter:
    def __init__(self) -> None:
        self._adapter: Any | None = None

    def _resolve(self) -> Any:
        if self._adapter is None:
            from app.adapters.guardrails_db import DbGuardrailAdapter

            self._adapter = DbGuardrailAdapter()
        return self._adapter

    async def evaluate_input(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> Any:
        adapter = self._resolve()
        return await adapter.evaluate_input(tenant_id=tenant_id, text=text, request_id=request_id)

    async def evaluate_output(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> Any:
        adapter = self._resolve()
        return await adapter.evaluate_output(tenant_id=tenant_id, text=text, request_id=request_id)


class _LazySemanticCacheAdapter:
    def __init__(self) -> None:
        self._adapter: Any | None = None

    def _resolve(self) -> Any:
        if self._adapter is None:
            from app.adapters.cache_pgvector import PgVectorSemanticCacheAdapter

            self._adapter = PgVectorSemanticCacheAdapter()
        return self._adapter

    async def lookup(self, key: Any) -> Any:
        adapter = self._resolve()
        return await adapter.lookup(key)

    async def store(self, key: Any, value: Any) -> None:
        adapter = self._resolve()
        await adapter.store(key, value)


@dataclass(frozen=True)
class Phase2Container:
    orchestrator: Orchestrator
    guardrails: GuardrailsAdapterLike
    semantic_cache: SemanticCacheAdapterLike
    telemetry: OTelTelemetryAdapter


def _load_agent_settings() -> Any:
    settings_module = importlib.import_module("agent_core.settings")
    return settings_module.get_settings()


def build_phase2_container() -> Phase2Container:
    settings = _load_agent_settings()
    return Phase2Container(
        orchestrator=execute,
        guardrails=_LazyGuardrailsAdapter(),
        semantic_cache=_LazySemanticCacheAdapter(),
        telemetry=OTelTelemetryAdapter(
            enabled=settings.otel_enabled,
            service_name=settings.otel_service_name,
        ),
    )
