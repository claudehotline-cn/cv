from __future__ import annotations

from typing import Any, Literal


def _extract_text(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    # Some providers return a list of blocks: [{"type":"text","text":"..."}, ...]
    if isinstance(content, list):
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text") or ""))
        return "".join(parts).strip()
    return str(content).strip()


def _normalize_role(raw: str | None) -> Literal["user", "assistant", "system"] | None:
    if not raw:
        return None
    r = raw.lower()
    if r in {"human", "user"}:
        return "user"
    if r in {"ai", "assistant"}:
        return "assistant"
    if r in {"system"}:
        return "system"
    return None


def normalize_message(msg: Any) -> dict[str, str] | None:
    """Normalize LangChain message objects / dicts into a tiny role+content shape."""
    if msg is None:
        return None

    raw_role: str | None = None
    content: Any = None

    if isinstance(msg, dict):
        raw_role = msg.get("role") or msg.get("type")
        content = msg.get("content")
    else:
        raw_role = getattr(msg, "role", None) or getattr(msg, "type", None)
        content = getattr(msg, "content", None)

        # Fallback: infer from class name
        if not raw_role:
            cls = getattr(msg, "__class__", None)
            name = getattr(cls, "__name__", "") if cls else ""
            if name in {"HumanMessage", "HumanMessageChunk"}:
                raw_role = "human"
            elif name in {"AIMessage", "AIMessageChunk"}:
                raw_role = "ai"
            elif name in {"SystemMessage", "SystemMessageChunk"}:
                raw_role = "system"

    role = _normalize_role(raw_role)
    if role is None:
        return None

    text = _extract_text(content)
    if not text:
        return None

    return {"role": role, "content": text}


def extract_recent_messages(state: Any, *, limit: int = 12) -> list[dict[str, str]]:
    """Extract recent user/assistant/system messages from a LangGraph state snapshot."""
    values: Any = None
    if isinstance(state, dict):
        values = state
    else:
        values = getattr(state, "values", None)

    if not isinstance(values, dict):
        return []

    raw_messages = values.get("messages")
    if not isinstance(raw_messages, list):
        return []

    normalized: list[dict[str, str]] = []
    for raw in raw_messages[-max(limit * 2, limit) :]:
        m = normalize_message(raw)
        if m is None:
            continue
        # Keep only the most useful roles for "shared memory".
        if m["role"] not in ("user", "assistant", "system"):
            continue
        normalized.append(m)

    return normalized[-limit:]


def format_recent_messages_for_prompt(messages: list[dict[str, str]]) -> str:
    if not messages:
        return ""
    role_map = {"user": "User", "assistant": "Assistant", "system": "System"}
    lines: list[str] = []
    for m in messages:
        role = role_map.get(m.get("role", ""), "Message")
        content = (m.get("content") or "").strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")
    return "\n".join(lines).strip()

