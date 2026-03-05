from collections.abc import Mapping
from dataclasses import dataclass
from typing import Literal


PolicyAction = Literal["allow", "block", "redact"]


@dataclass(frozen=True)
class PolicyDecision:
    action: PolicyAction = "allow"
    reason_code: str | None = None
    payload: Mapping[str, object] | None = None
    sanitized_payload: Mapping[str, object] | None = None
