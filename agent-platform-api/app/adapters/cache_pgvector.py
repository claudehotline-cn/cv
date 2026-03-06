from __future__ import annotations

import importlib
import json
from collections.abc import Mapping
from typing import Any, Callable

from sqlalchemy import text  # pyright: ignore[reportMissingImports]

from app.platform_core.models import SemanticCacheKey, SemanticCacheValue
from app.db import AsyncSessionLocal


def _load_agent_settings() -> Any:
    settings_module = importlib.import_module("agent_core.settings")
    return settings_module.get_settings()


class PgVectorSemanticCacheAdapter:
    """Postgres/pgvector semantic cache adapter for Phase2."""

    def __init__(
        self,
        session_factory: Callable[[], Any] | None = None,
        *,
        ttl_seconds: int | None = None,
        similarity_threshold: float | None = None,
        enabled: bool | None = None,
    ) -> None:
        settings = _load_agent_settings()
        self._session_factory = session_factory or AsyncSessionLocal
        self._enabled = settings.semantic_cache_enabled if enabled is None else enabled
        self._ttl_seconds = settings.semantic_cache_ttl_seconds if ttl_seconds is None else ttl_seconds
        self._similarity_threshold = (
            settings.semantic_cache_similarity_threshold
            if similarity_threshold is None
            else similarity_threshold
        )

    async def lookup(self, key: SemanticCacheKey) -> SemanticCacheValue | None:
        if not self._enabled:
            return None

        tenant_id = getattr(key, "tenant_id", None)
        if not tenant_id:
            return None

        namespace = str(getattr(key, "namespace", "default"))
        prompt_hash = str(getattr(key, "prompt_hash", ""))
        model_key = self._extract_model_key(key)

        async with self._session_factory() as session:
            if model_key is None:
                result = await session.execute(
                    text(
                        """
                        SELECT id, response, metadata
                        FROM semantic_cache_entries
                        WHERE tenant_id::text = :tenant_id
                          AND namespace = :namespace
                          AND prompt_hash = :prompt_hash
                          AND created_at >= NOW() - make_interval(secs => :ttl_seconds)
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "namespace": namespace,
                        "prompt_hash": prompt_hash,
                        "ttl_seconds": int(self._ttl_seconds),
                    },
                )
            else:
                result = await session.execute(
                    text(
                        """
                        SELECT id, response, metadata
                        FROM semantic_cache_entries
                        WHERE tenant_id::text = :tenant_id
                          AND namespace = :namespace
                          AND prompt_hash = :prompt_hash
                          AND COALESCE(metadata->>'model_key', '') = :model_key
                          AND created_at >= NOW() - make_interval(secs => :ttl_seconds)
                        ORDER BY updated_at DESC
                        LIMIT 1
                        """
                    ),
                    {
                        "tenant_id": tenant_id,
                        "namespace": namespace,
                        "prompt_hash": prompt_hash,
                        "model_key": model_key,
                        "ttl_seconds": int(self._ttl_seconds),
                    },
                )
            row = result.mappings().first()

            if row is None:
                row = await self._lookup_by_vector(
                    session,
                    tenant_id=tenant_id,
                    namespace=namespace,
                    model_key=model_key,
                    key=key,
                )

            if row is None:
                return None

            await self._increment_hit_count(session, row.get("id"))
            return SemanticCacheValue(
                response=str(row.get("response") or ""),
                metadata=self._normalize_metadata(row.get("metadata")),
            )

    async def store(self, key: SemanticCacheKey, value: SemanticCacheValue) -> None:
        if not self._enabled:
            return

        tenant_id = getattr(key, "tenant_id", None)
        if not tenant_id:
            return

        namespace = str(getattr(key, "namespace", "default"))
        prompt_hash = str(getattr(key, "prompt_hash", ""))
        model_key = self._extract_model_key(key)

        metadata: dict[str, Any] = dict(value.metadata or {})
        if model_key:
            metadata.setdefault("model_key", model_key)
        metadata.setdefault("hit_count", 0)

        embedding_literal = self._embedding_literal(getattr(key, "embedding", None))

        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO semantic_cache_entries (
                        id,
                        tenant_id,
                        namespace,
                        prompt_hash,
                        response,
                        metadata,
                        embedding,
                        created_at,
                        updated_at
                    ) VALUES (
                        gen_random_uuid(),
                        CAST(:tenant_id AS UUID),
                        :namespace,
                        :prompt_hash,
                        :response,
                        CAST(:metadata_json AS JSONB),
                        CAST(:embedding AS vector),
                        NOW(),
                        NOW()
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "prompt_hash": prompt_hash,
                    "response": value.response,
                    "metadata_json": json.dumps(metadata),
                    "embedding": embedding_literal,
                },
            )

            await session.execute(
                text(
                    """
                    DELETE FROM semantic_cache_entries
                    WHERE tenant_id::text = :tenant_id
                      AND namespace = :namespace
                      AND created_at < NOW() - make_interval(secs => :ttl_seconds)
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "ttl_seconds": int(self._ttl_seconds),
                },
            )

    async def _lookup_by_vector(
        self,
        session: Any,
        *,
        tenant_id: str,
        namespace: str,
        model_key: str | None,
        key: SemanticCacheKey,
    ) -> dict[str, Any] | None:
        embedding_literal = self._embedding_literal(getattr(key, "embedding", None))
        if embedding_literal is None:
            return None

        if model_key is None:
            result = await session.execute(
                text(
                    """
                    SELECT id, response, metadata
                    FROM semantic_cache_entries
                    WHERE tenant_id::text = :tenant_id
                      AND namespace = :namespace
                      AND embedding IS NOT NULL
                      AND created_at >= NOW() - make_interval(secs => :ttl_seconds)
                      AND (embedding <=> CAST(:embedding AS vector)) <= :similarity_threshold
                    ORDER BY embedding <=> CAST(:embedding AS vector) ASC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "embedding": embedding_literal,
                    "ttl_seconds": int(self._ttl_seconds),
                    "similarity_threshold": float(self._similarity_threshold),
                },
            )
        else:
            result = await session.execute(
                text(
                    """
                    SELECT id, response, metadata
                    FROM semantic_cache_entries
                    WHERE tenant_id::text = :tenant_id
                      AND namespace = :namespace
                      AND COALESCE(metadata->>'model_key', '') = :model_key
                      AND embedding IS NOT NULL
                      AND created_at >= NOW() - make_interval(secs => :ttl_seconds)
                      AND (embedding <=> CAST(:embedding AS vector)) <= :similarity_threshold
                    ORDER BY embedding <=> CAST(:embedding AS vector) ASC
                    LIMIT 1
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "namespace": namespace,
                    "model_key": model_key,
                    "embedding": embedding_literal,
                    "ttl_seconds": int(self._ttl_seconds),
                    "similarity_threshold": float(self._similarity_threshold),
                },
            )
        return result.mappings().first()

    async def _increment_hit_count(self, session: Any, cache_id: Any) -> None:
        if cache_id is None:
            return

        await session.execute(
            text(
                """
                UPDATE semantic_cache_entries
                SET metadata = jsonb_set(
                        COALESCE(metadata, '{}'::jsonb),
                        '{hit_count}',
                        to_jsonb(COALESCE((metadata->>'hit_count')::int, 0) + 1)::jsonb,
                        true
                    ),
                    updated_at = NOW()
                WHERE id = :cache_id
                """
            ),
            {"cache_id": cache_id},
        )

    def _extract_model_key(self, key: SemanticCacheKey) -> str | None:
        model_key = getattr(key, "model_key", None)
        if model_key is None:
            return None
        text_value = str(model_key).strip()
        return text_value or None

    def _embedding_literal(self, embedding: Any) -> str | None:
        if embedding is None:
            return None
        if not isinstance(embedding, list):
            return None
        values: list[str] = []
        for item in embedding:
            if isinstance(item, (int, float)):
                values.append(str(float(item)))
        if not values:
            return None
        return "[" + ",".join(values) + "]"

    def _normalize_metadata(self, metadata: Any) -> Mapping[str, str]:
        if not isinstance(metadata, dict):
            return {}
        normalized: dict[str, str] = {}
        for key, value in metadata.items():
            normalized[str(key)] = "" if value is None else str(value)
        return normalized
