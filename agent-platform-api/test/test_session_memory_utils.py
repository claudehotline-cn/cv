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
def test_extract_recent_messages_from_state_values() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    mod = _load_module(
        "session_memory",
        repo_root / "agent-platform-api/app/utils/session_memory.py",
    )

    class _State:
        def __init__(self, values):
            self.values = values

    state = _State(
        values={
            "messages": [
                {"role": "user", "content": "hi"},
                {"role": "assistant", "content": "hello"},
                {"role": "tool", "content": "ignored"},
            ]
        }
    )
    assert mod.extract_recent_messages(state, limit=10) == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


@pytest.mark.unit
def test_format_recent_messages_for_prompt() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    mod = _load_module(
        "session_memory",
        repo_root / "agent-platform-api/app/utils/session_memory.py",
    )

    text = mod.format_recent_messages_for_prompt(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": "hello"},
        ]
    )
    assert "User: hi" in text
    assert "Assistant: hello" in text

