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
    last_error: Optional[str]
    updated_at: str


_THREAD_SUMMARIES: Dict[str, ThreadSummary] = {}
_AGENT_STATS: Dict[tuple, Dict[str, int]] = {}
# Tool 维度统计：按 tool_name 聚合调用次数与总耗时
_TOOL_STATS: Dict[str, Dict[str, float]] = {}


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
        last_error=existing.last_error if existing else None,
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
        last_error=control_result.error if not control_result.success else (existing.last_error if existing else None),
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


def record_tool_call(
    tool_name: str,
    *,
    success: bool,
    elapsed_ms: float,
) -> None:
    """记录单次工具调用的成功/失败与耗时，用于后续统计与可观测性。"""

    stat = _TOOL_STATS.setdefault(
        tool_name,
        {
            "success": 0.0,
            "failure": 0.0,
            "total_ms": 0.0,
        },
    )
    if success:
        stat["success"] += 1.0
    else:
        stat["failure"] += 1.0
    if elapsed_ms >= 0.0:
        stat["total_ms"] += float(elapsed_ms)


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
    """返回 Agent 控制操作与 Tool 调用的基础统计信息。"""

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

    for tool_name, stat in _TOOL_STATS.items():
        total_calls = stat.get("success", 0.0) + stat.get("failure", 0.0)
        avg_latency = stat["total_ms"] / total_calls if total_calls > 0 else 0.0
        out.append(
            {
                "op": f"tool.{tool_name}",
                "mode": "invoke",
                "success_count": int(stat.get("success", 0.0)),
                "failure_count": int(stat.get("failure", 0.0)),
                "avg_latency_ms": avg_latency,
            }
        )

    out.sort(key=lambda x: (x["op"], x["mode"]))
    return out
