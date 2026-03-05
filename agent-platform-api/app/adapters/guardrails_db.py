from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy import text  # pyright: ignore[reportMissingImports]

from app.platform_core.models import GuardrailInput, GuardrailResult

from app.db import AsyncSessionLocal


_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
_PHONE_RE = re.compile(r"\b(?:\+?\d{1,3}[\s.-]?)?(?:\(?\d{3}\)?[\s.-]?)\d{3}[\s.-]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


@dataclass(frozen=True)
class GuardrailDecision:
    action: str = "allow"
    reason_code: str | None = None
    payload: dict[str, Any] | None = None
    sanitized_text: str | None = None


class DbGuardrailAdapter:
    """DB-backed guardrail adapter with minimal keyword/PII enforcement."""

    def __init__(self, session_factory: Callable[[], Any] | None = None) -> None:
        self._session_factory = session_factory or AsyncSessionLocal

    async def evaluate(self, payload: GuardrailInput) -> GuardrailResult:
        decision = await self.evaluate_input(
            tenant_id=payload.tenant_id,
            text=payload.prompt,
            request_id=payload.metadata.get("request_id"),
        )
        return GuardrailResult(
            allowed=decision.action != "block",
            reason=decision.reason_code,
        )

    async def evaluate_input(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> GuardrailDecision:
        policy = await self._load_policy(tenant_id)
        if not policy["enabled"]:
            return GuardrailDecision(action="allow")

        lowered = text.lower()
        keywords = self._string_list(policy["config"].get("input_block_keywords"))
        for keyword in keywords:
            if keyword.lower() in lowered:
                decision = GuardrailDecision(
                    action="block",
                    reason_code="input_keyword_block",
                    payload={"matched_keyword": keyword},
                )
                return await self._finalize_decision(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    direction="input",
                    decision=decision,
                    mode=policy["mode"],
                    text_value=text,
                )

        if bool(policy["config"].get("detect_pii", True)) and self._contains_pii(text):
            decision = GuardrailDecision(
                action="block",
                reason_code="input_pii_block",
                payload={"pii_detected": True},
            )
            return await self._finalize_decision(
                tenant_id=tenant_id,
                request_id=request_id,
                direction="input",
                decision=decision,
                mode=policy["mode"],
                text_value=text,
            )

        return GuardrailDecision(action="allow")

    async def evaluate_output(
        self,
        *,
        tenant_id: str | None,
        text: str,
        request_id: str | None = None,
    ) -> GuardrailDecision:
        policy = await self._load_policy(tenant_id)
        if not policy["enabled"]:
            return GuardrailDecision(action="allow")

        lowered = text.lower()
        approval_keywords = self._string_list(
            policy["config"].get("output_approval_keywords")
            or policy["config"].get("require_approval_keywords")
        )
        for keyword in approval_keywords:
            if keyword.lower() in lowered:
                decision = GuardrailDecision(
                    action="require_approval",
                    reason_code="output_requires_approval",
                    payload={"matched_keyword": keyword},
                )
                return await self._finalize_decision(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    direction="output",
                    decision=decision,
                    mode=policy["mode"],
                    text_value=text,
                )

        redact_keywords = self._string_list(policy["config"].get("output_redact_keywords"))
        for keyword in redact_keywords:
            if keyword.lower() in lowered:
                decision = GuardrailDecision(
                    action="redact",
                    reason_code="output_keyword_redact",
                    payload={"matched_keyword": keyword},
                    sanitized_text=text.replace(keyword, "[REDACTED]"),
                )
                return await self._finalize_decision(
                    tenant_id=tenant_id,
                    request_id=request_id,
                    direction="output",
                    decision=decision,
                    mode=policy["mode"],
                    text_value=text,
                )

        if bool(policy["config"].get("detect_pii", True)) and self._contains_pii(text):
            decision = GuardrailDecision(
                action="redact",
                reason_code="output_pii_redact",
                payload={"pii_detected": True},
                sanitized_text=self._redact_pii(text),
            )
            return await self._finalize_decision(
                tenant_id=tenant_id,
                request_id=request_id,
                direction="output",
                decision=decision,
                mode=policy["mode"],
                text_value=text,
            )

        return GuardrailDecision(action="allow")

    async def _load_policy(self, tenant_id: str | None) -> dict[str, Any]:
        if not tenant_id:
            return {"enabled": False, "mode": "enforce", "config": {}}

        async with self._session_factory() as session:
            result = await session.execute(
                text(
                    """
                    SELECT enabled, mode, config
                    FROM tenant_guardrail_policies
                    WHERE tenant_id::text = :tenant_id
                    LIMIT 1
                    """
                ),
                {"tenant_id": tenant_id},
            )
            row = result.mappings().first()

        if row is None:
            return {"enabled": True, "mode": "enforce", "config": {}}

        return {
            "enabled": bool(row.get("enabled", True)),
            "mode": str(row.get("mode") or "enforce"),
            "config": dict(row.get("config") or {}),
        }

    async def _finalize_decision(
        self,
        *,
        tenant_id: str | None,
        request_id: str | None,
        direction: str,
        decision: GuardrailDecision,
        mode: str,
        text_value: str,
    ) -> GuardrailDecision:
        if decision.action in {"block", "redact", "require_approval"}:
            await self._persist_event(
                tenant_id=tenant_id,
                request_id=request_id,
                direction=direction,
                decision=decision,
                text_value=text_value,
            )

        if mode == "monitor" and decision.action in {"block", "redact", "require_approval"}:
            return GuardrailDecision(action="allow", reason_code=decision.reason_code, payload=decision.payload)

        return decision

    async def _persist_event(
        self,
        *,
        tenant_id: str | None,
        request_id: str | None,
        direction: str,
        decision: GuardrailDecision,
        text_value: str,
    ) -> None:
        if not tenant_id:
            return

        event_payload = {
            "preview": text_value[:200],
            "detail": decision.payload or {},
        }
        if decision.sanitized_text is not None:
            event_payload["sanitized_preview"] = decision.sanitized_text[:200]

        async with self._session_factory() as session:
            await session.execute(
                text(
                    """
                    INSERT INTO guardrail_events (
                        id,
                        tenant_id,
                        request_id,
                        direction,
                        action,
                        reason_code,
                        payload,
                        created_at
                    ) VALUES (
                        gen_random_uuid(),
                        CAST(:tenant_id AS UUID),
                        CAST(:request_id AS UUID),
                        :direction,
                        :action,
                        :reason_code,
                        CAST(:payload_json AS JSONB),
                        NOW()
                    )
                    """
                ),
                {
                    "tenant_id": tenant_id,
                    "request_id": request_id,
                    "direction": direction,
                    "action": decision.action,
                    "reason_code": decision.reason_code,
                    "payload_json": json.dumps(event_payload),
                },
            )

    def _contains_pii(self, text_value: str) -> bool:
        return bool(_EMAIL_RE.search(text_value) or _PHONE_RE.search(text_value) or _SSN_RE.search(text_value))

    def _redact_pii(self, text_value: str) -> str:
        text_value = _EMAIL_RE.sub("[REDACTED_EMAIL]", text_value)
        text_value = _PHONE_RE.sub("[REDACTED_PHONE]", text_value)
        text_value = _SSN_RE.sub("[REDACTED_SSN]", text_value)
        return text_value

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                result.append(item)
        return result
