from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict
from uuid import uuid4

import redis.asyncio as aioredis

from app.core.config import get_settings
from app.core.security import sha256_hex


def _utc_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class AuthAuditEmitter:
    def __init__(self):
        settings = get_settings()
        self._stream_key = settings.auth_audit_stream_key
        self._redis = aioredis.from_url(settings.auth_redis_url, decode_responses=True)

    async def emit(
        self,
        *,
        event_type: str,
        actor_id: str,
        actor_type: str = "user",
        payload: Dict[str, Any] | None = None,
    ) -> None:
        body = payload or {}
        fields = {
            "event_id": str(uuid4()),
            "event_type": event_type,
            "component": "auth",
            "actor_type": actor_type,
            "actor_id": actor_id,
            "event_time": str(datetime.now(timezone.utc).timestamp()),
            "payload_json": self._sanitize_payload(body),
            # Keep request_id non-empty for backward compatibility with existing stream consumers.
            "request_id": f"auth-{sha256_hex(event_type + actor_id + _utc_iso())[:32]}",
            "span_id": "",
            "session_id": "",
            "thread_id": "",
        }
        await self._redis.xadd(self._stream_key, fields, maxlen=100000, approximate=True)

    @staticmethod
    def _sanitize_payload(payload: Dict[str, Any]) -> str:
        import json

        blocked = {"password", "current_password", "new_password", "refresh_token", "access_token", "key"}
        sanitized = {}
        for k, v in payload.items():
            if k in blocked:
                continue
            sanitized[k] = v
        return json.dumps(sanitized, ensure_ascii=False)


_audit_emitter: AuthAuditEmitter | None = None


def get_auth_audit_emitter() -> AuthAuditEmitter:
    global _audit_emitter
    if _audit_emitter is None:
        _audit_emitter = AuthAuditEmitter()
    return _audit_emitter
