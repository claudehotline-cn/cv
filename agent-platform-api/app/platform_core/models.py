from dataclasses import dataclass, field
from typing import Mapping


@dataclass(frozen=True)
class GuardrailInput:
    prompt: str
    tenant_id: str | None = None
    user_id: str | None = None
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    reason: str | None = None


@dataclass(frozen=True)
class SemanticCacheKey:
    prompt_hash: str
    tenant_id: str | None = None
    namespace: str = "default"


@dataclass(frozen=True)
class SemanticCacheValue:
    response: str
    metadata: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class TelemetryMetric:
    name: str
    value: float
    attributes: Mapping[str, str] = field(default_factory=dict)
