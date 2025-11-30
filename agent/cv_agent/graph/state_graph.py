from typing import Any, Dict, List, Optional

from langchain_core.messages import BaseMessage
from pydantic import BaseModel, Field


class AgentState(BaseModel):
    """
    AgentState 定义了控制平面 Agent 在 LangGraph 中使用的统一状态结构。

    设计目标：
    - 与 LangGraph 1.x 的 StateGraph 兼容（作为 state 类型）；
    - 覆盖后续多 Agent 拆分所需的核心字段；
    - 便于在 checkpoint 中持久化并在前端展示。
    """

    # 对话消息流（LangChain 消息对象列表）
    messages: List[BaseMessage] = Field(default_factory=list)

    # 用户上下文：从 HTTP 头部透传的 user_id / role / tenant 等
    user: Dict[str, Any] = Field(default_factory=dict)

    # 当前 CV 上下文，例如 pipeline/model/VA 状态快照
    cv_context: Dict[str, Any] = Field(default_factory=dict)

    # 对复杂任务的显式计划（步骤列表），后续可在多 Agent 场景中用于展示/执行
    plan: List[str] = Field(default_factory=list)

    # 待执行的工具调用队列（保留扩展位，当前实现中暂未使用）
    pending_tools: List[Dict[str, Any]] = Field(default_factory=list)

    # 当前任务/路由意图（例如 pipeline/debug/model），由 Router 节点判定
    task: Optional[str] = Field(default=None)

    # 可选：最近一次控制操作摘要（便于在前端/审计中快速展示）
    last_control_op: Optional[str] = Field(default=None)
    last_control_mode: Optional[str] = Field(default=None)
    last_control_result: Optional[Dict[str, Any]] = Field(default=None)


__all__ = ["AgentState"]
