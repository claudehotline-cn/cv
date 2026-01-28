from __future__ import annotations

import json
import logging
import time
import uuid
import asyncio
import inspect
from dataclasses import dataclass
from typing import Any, Dict, Mapping, Optional

_LOGGER = logging.getLogger("agent_audit.emitter")


@dataclass
class AuditEmitter:
    """Emit standardized audit events.

    Default transport is Redis Streams (xadd) when `redis` is provided.

    Notes:
    - This mirrors the existing `agent_core.events.AuditEmitter` API to keep integration simple.
    - Future transports (Kafka/HTTP) should be implemented behind a dedicated transport interface.
    """

    redis: Any
    stream_key: str = "audit.events"

    async def emit(
        self,
        *,
        event_type: str,
        request_id: str,
        span_id: str | None,
        session_id: str | None = None,
        thread_id: str | None = None,
        parent_span_id: str | None = None,
        component: str | None = None,
        payload: Dict[str, Any] | None = None,
        actor_type: str = "agent",
        actor_id: str = "worker",
        extra_fields: Optional[Mapping[str, Any]] = None,
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
            "component": component or "",
            "actor_type": actor_type,
            "actor_id": actor_id,
            "payload_json": json.dumps(payload, ensure_ascii=False),
        }
        if extra_fields:
            fields.update(dict(extra_fields))

        try:
            xadd = getattr(self.redis, "xadd", None)
            if xadd is None:
                raise AttributeError("redis client has no xadd()")

            if inspect.iscoroutinefunction(xadd):
                await xadd(self.stream_key, fields, maxlen=100000, approximate=True)
            else:
                await asyncio.to_thread(xadd, self.stream_key, fields, maxlen=100000, approximate=True)
        except Exception as exc:
            _LOGGER.error("Failed to emit audit event %s: %s", event_type, exc)
