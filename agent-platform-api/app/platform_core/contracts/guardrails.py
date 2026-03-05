from typing import Protocol, runtime_checkable

from app.platform_core.models import GuardrailInput, GuardrailResult


@runtime_checkable
class GuardrailsPort(Protocol):
    async def evaluate(self, payload: GuardrailInput) -> GuardrailResult:
        ...
