import sys
from pathlib import Path


def _ensure_agent_auth_on_path() -> None:
    root = Path(__file__).resolve().parents[2]
    path = str(root)
    if path not in sys.path:
        sys.path.insert(0, path)


_ensure_agent_auth_on_path()
