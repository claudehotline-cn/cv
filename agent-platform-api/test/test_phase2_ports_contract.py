from collections.abc import Mapping
from dataclasses import is_dataclass

from app.platform_core.contracts.guardrails import GuardrailsPort
from app.platform_core.contracts.semantic_cache import SemanticCachePort
from app.platform_core.contracts.telemetry import TelemetryPort
from app.platform_core.models import (
    GuardrailResult,
    GuardrailInput,
    SemanticCacheKey,
    SemanticCacheValue,
    TelemetryMetric,
)


def test_phase2_symbols_are_available_from_platform_core() -> None:
    expected = {
        "GuardrailsPort",
        "SemanticCachePort",
        "TelemetryPort",
        "GuardrailInput",
        "GuardrailResult",
        "SemanticCacheKey",
        "SemanticCacheValue",
        "TelemetryMetric",
    }

    actual = {
        "GuardrailsPort",
        "SemanticCachePort",
        "TelemetryPort",
        "GuardrailInput",
        "GuardrailResult",
        "SemanticCacheKey",
        "SemanticCacheValue",
        "TelemetryMetric",
    }

    assert expected.issubset(actual)


def test_phase2_models_are_dataclasses() -> None:
    assert is_dataclass(GuardrailInput)
    assert is_dataclass(GuardrailResult)
    assert is_dataclass(SemanticCacheKey)
    assert is_dataclass(SemanticCacheValue)
    assert is_dataclass(TelemetryMetric)


def test_phase2_ports_are_runtime_protocols() -> None:
    class GuardrailsAdapter:
        async def evaluate(self, payload):
            _ = payload
            return GuardrailResult(allowed=True)

    class SemanticCacheAdapter:
        async def lookup(self, key):
            _ = key
            return None

        async def store(self, key, value) -> None:
            _ = (key, value)
            return None

    class TelemetryAdapter:
        def increment(self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None) -> None:
            _ = (name, value, attributes)
            return None

        def record_latency_ms(self, name: str, value_ms: float, attributes: Mapping[str, str] | None = None) -> None:
            _ = (name, value_ms, attributes)
            return None

    assert isinstance(GuardrailsAdapter(), GuardrailsPort)
    assert isinstance(SemanticCacheAdapter(), SemanticCachePort)
    assert isinstance(TelemetryAdapter(), TelemetryPort)
