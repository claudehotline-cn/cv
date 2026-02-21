from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Dict, Optional


_LOGGER = logging.getLogger("rag_service.audit_emitter")


class AuditEmitter:
    """Emit audit events to Redis Streams (compatible with agent platform consumer)."""

    def __init__(self, redis: Any, *, stream_key: str = "audit.events"):
        self.redis = redis
        self.stream_key = stream_key

    async def emit(
        self,
        *,
        event_type: str,
        request_id: str,
        span_id: Optional[str],
        session_id: Optional[str] = None,
        thread_id: Optional[str] = None,
        parent_span_id: Optional[str] = None,
        component: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        actor_type: str = "service",
        actor_id: str = "rag-service",
    ) -> None:
        if payload is None:
            payload = {}

        fields: Dict[str, Any] = {
            "event_id": str(uuid.uuid4()),
            "schema_version": "1",
            "event_type": event_type,
            "event_time": str(time.time()),
            "request_id": str(request_id) if request_id else "unknown",
            "session_id": str(session_id) if session_id else "",
            "thread_id": str(thread_id) if thread_id else "",
            "span_id": str(span_id) if span_id else "",
            "parent_span_id": str(parent_span_id) if parent_span_id else "",
            "component": component or "rag",
            "actor_type": actor_type,
            "actor_id": actor_id,
            "payload_json": json.dumps(payload, ensure_ascii=False),
        }

        try:
            await self.redis.xadd(self.stream_key, fields, maxlen=100000, approximate=True)
        except Exception as exc:
            _LOGGER.error("Failed to emit audit event %s: %s", event_type, exc)
