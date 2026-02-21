from __future__ import annotations

from typing import Any


def extract_interrupt_data(state: Any) -> list[Any] | None:
    """Extract LangGraph/DeepAgents interrupt payload from a StateSnapshot.

    We support both:
    - `state.tasks[*].interrupts` (newer LangGraph)
    - `state.values["__interrupt__"]` (legacy / fallback)
    """
    if state is None:
        return None

    # Preferred: state.tasks[*].interrupts
    tasks = getattr(state, "tasks", None)
    if tasks:
        for task in tasks:
            interrupts = getattr(task, "interrupts", None)
            if not interrupts:
                continue
            extracted: list[Any] = []
            for i in interrupts:
                extracted.append(getattr(i, "value", i))
            if extracted:
                return extracted

    # Fallback: state.values["__interrupt__"]
    values = getattr(state, "values", None)
    if isinstance(values, dict) and "__interrupt__" in values:
        data = values.get("__interrupt__")
        if data:
            return data if isinstance(data, list) else [data]

    return None

