from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


@dataclass
class ThreadSummary:
    """线程级摘要信息，用于按 thread_id 快速查看最近对话与控制结果。"""

    thread_id: str
    user_id: Optional[str]
    role: Optional[str]
    tenant: Optional[str]
    last_user_message: Optional[str]
    last_assistant_message: Optional[str]
    last_control_op: Optional[str]
    last_control_mode: Optional[str]
    last_control_success: Optional[bool]
    updated_at: str


_THREAD_SUMMARIES: Dict[str, ThreadSummary] = {}
_AGENT_STATS: Dict[tuple, Dict[str, int]] = {}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def update_summary_for_messages(
    *,
    thread_id: Optional[str],
    user: Any,
    messages: List[Any],
) -> None:
    """根据最新对话消息更新线程摘要（不包含控制结果）。"""

    if not thread_id:
        return

    last_user = None
    last_assistant = None
    for m in messages:
        if m.role == "user":
            last_user = m.content
        elif m.role == "assistant":
            last_assistant = m.content

    existing = _THREAD_SUMMARIES.get(thread_id)
    summary = ThreadSummary(
        thread_id=thread_id,
        user_id=user.user_id,
        role=user.role,
        tenant=user.tenant,
        last_user_message=last_user or (existing.last_user_message if existing else None),
        last_assistant_message=last_assistant
        or (existing.last_assistant_message if existing else None),
        last_control_op=existing.last_control_op if existing else None,
        last_control_mode=existing.last_control_mode if existing else None,
        last_control_success=existing.last_control_success if existing else None,
        updated_at=_now_iso(),
    )
    _THREAD_SUMMARIES[thread_id] = summary


def update_summary_for_control(
    *,
    thread_id: Optional[str],
    user: Any,
    control_result: Any,
) -> None:
    """在执行 control 协议后更新线程摘要中的控制相关字段。"""

    if not thread_id:
        return

    existing = _THREAD_SUMMARIES.get(thread_id)
    summary = ThreadSummary(
        thread_id=thread_id,
        user_id=user.user_id,
        role=user.role,
        tenant=user.tenant,
        last_user_message=existing.last_user_message if existing else None,
        last_assistant_message=existing.last_assistant_message if existing else None,
        last_control_op=control_result.op,
        last_control_mode=control_result.mode,
        last_control_success=control_result.success,
        updated_at=_now_iso(),
    )
    _THREAD_SUMMARIES[thread_id] = summary

    # 更新全局控制操作统计
    key = (control_result.op, control_result.mode)
    stat = _AGENT_STATS.setdefault(key, {"success": 0, "failure": 0})
    if control_result.success:
        stat["success"] += 1
    else:
        stat["failure"] += 1


def get_thread_summary(thread_id: str) -> Optional[Dict[str, Any]]:
    summary = _THREAD_SUMMARIES.get(thread_id)
    if summary is None:
        return None
    return asdict(summary)


def list_thread_summaries(limit: int = 50) -> List[Dict[str, Any]]:
    """按更新时间倒序返回线程摘要列表。"""

    items = list(_THREAD_SUMMARIES.values())
    items.sort(key=lambda s: s.updated_at, reverse=True)
    return [asdict(s) for s in items[:limit]]


def get_agent_stats() -> List[Dict[str, Any]]:
    """返回 Agent 控制操作按 (op, mode) 聚合的计数。"""

    out: List[Dict[str, Any]] = []
    for (op, mode), stat in _AGENT_STATS.items():
        out.append(
            {
                "op": op,
                "mode": mode,
                "success_count": stat.get("success", 0),
                "failure_count": stat.get("failure", 0),
            }
        )
    out.sort(key=lambda x: (x["op"], x["mode"]))
    return out
