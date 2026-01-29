import importlib.util
from pathlib import Path

import pytest


def _load_module(module_name: str, path: Path):
    spec = importlib.util.spec_from_file_location(module_name, str(path))
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    return mod


@pytest.mark.unit
def test_extract_interrupt_data_from_tasks() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    mod = _load_module(
        "interrupts",
        repo_root / "agent-platform-api/app/utils/interrupts.py",
    )

    class _Interrupt:
        def __init__(self, value):
            self.value = value

    class _Task:
        def __init__(self, interrupts):
            self.interrupts = interrupts

    class _State:
        def __init__(self, tasks=None, values=None):
            self.tasks = tasks
            self.values = values

    state = _State(tasks=[_Task([_Interrupt({"question": "approve?"})])], values={})
    assert mod.extract_interrupt_data(state) == [{"question": "approve?"}]


@pytest.mark.unit
def test_extract_interrupt_data_from_values_fallback() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    mod = _load_module(
        "interrupts",
        repo_root / "agent-platform-api/app/utils/interrupts.py",
    )

    class _State:
        def __init__(self, tasks=None, values=None):
            self.tasks = tasks
            self.values = values

    state = _State(tasks=None, values={"__interrupt__": {"k": "v"}})
    assert mod.extract_interrupt_data(state) == [{"k": "v"}]

