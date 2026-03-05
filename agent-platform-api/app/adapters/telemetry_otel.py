from __future__ import annotations

import importlib
import logging
from collections.abc import Mapping
from typing import Any

from agent_core.observability import NoopSpan  # pyright: ignore[reportMissingImports]


_LOGGER = logging.getLogger(__name__)


def _load_opentelemetry() -> tuple[Any, Any]:
    otel_mod = importlib.import_module("opentelemetry")  # pyright: ignore[reportMissingImports]
    metrics = getattr(otel_mod, "metrics")
    trace = getattr(otel_mod, "trace")
    return metrics, trace


def _set_span_attribute(span_obj: Any, key: str, value: str) -> None:
    setter = getattr(span_obj, "set_attribute", None)
    if callable(setter):
        setter(key, value)


class _SpanAdapter:
    def __init__(self, span_cm: Any, attributes: Mapping[str, str] | None = None) -> None:
        self._span_cm = span_cm
        self._attributes = dict(attributes or {})

    def __enter__(self) -> "_SpanAdapter":
        enter = getattr(self._span_cm, "__enter__", None)
        if callable(enter):
            span_obj = enter()
            if span_obj is not None:
                for key, value in self._attributes.items():
                    try:
                        _set_span_attribute(span_obj, str(key), str(value))
                    except Exception:
                        pass
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> bool | None:
        exit_fn = getattr(self._span_cm, "__exit__", None)
        if callable(exit_fn):
            result = exit_fn(exc_type, exc, tb)
            if isinstance(result, bool) or result is None:
                return result
            return False
        return False


class OTelTelemetryAdapter:
    """Telemetry adapter implementing orchestrator telemetry surface."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        service_name: str = "agent-platform-api",
    ) -> None:
        self._enabled = enabled
        self._service_name = service_name
        self._tracer: Any | None = None
        self._counters: dict[str, Any] = {}
        self._histograms: dict[str, Any] = {}

        if not enabled:
            return

        try:
            metrics, trace = _load_opentelemetry()

            self._tracer = trace.get_tracer(service_name)
            self._meter = metrics.get_meter(service_name)
        except Exception as exc:  # pragma: no cover - exercised in integration env
            self._enabled = False
            self._tracer = None
            self._meter = None
            _LOGGER.debug("OTel unavailable, telemetry adapter in noop mode: %s", exc)

    def start_span(self, name: str, attributes: Mapping[str, str] | None = None):
        if not self._enabled or self._tracer is None:
            return NoopSpan()

        span_cm = self._tracer.start_as_current_span(name)
        return _SpanAdapter(span_cm, attributes=attributes)

    def increment(self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None) -> None:
        self.counter(name, value=value, attributes=attributes)

    def counter(self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None) -> None:
        if not self._enabled:
            return

        meter = getattr(self, "_meter", None)
        if meter is None:
            return

        counter = self._counters.get(name)
        if counter is None:
            counter = meter.create_counter(name)
            self._counters[name] = counter

        counter.add(int(value), attributes=dict(attributes or {}))

    def record_latency_ms(self, name: str, value_ms: float, attributes: Mapping[str, str] | None = None) -> None:
        self.histogram(name, value=value_ms, attributes=attributes)

    def histogram(self, name: str, value: float, attributes: Mapping[str, str] | None = None) -> None:
        if not self._enabled:
            return

        meter = getattr(self, "_meter", None)
        if meter is None:
            return

        histogram = self._histograms.get(name)
        if histogram is None:
            histogram = meter.create_histogram(name)
            self._histograms[name] = histogram

        histogram.record(float(value), attributes=dict(attributes or {}))
