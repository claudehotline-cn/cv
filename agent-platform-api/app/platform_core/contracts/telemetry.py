from typing import Mapping, Protocol, runtime_checkable


@runtime_checkable
class TelemetryPort(Protocol):
    def increment(self, name: str, value: int = 1, attributes: Mapping[str, str] | None = None) -> None:
        ...

    def record_latency_ms(self, name: str, value_ms: float, attributes: Mapping[str, str] | None = None) -> None:
        ...
