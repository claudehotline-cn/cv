"""Infrastructure - LangGraph Agent Adapter.

将现有的 Deep Agent 适配为 IAgentRunner 接口。
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional
from uuid import uuid4

from ..domain.entities import EventType, FeedbackRequest, Message, MessageRole, Session, StreamEvent

if TYPE_CHECKING:
    pass

_LOGGER = logging.getLogger(__name__)


class LangGraphAgentAdapter:
    """LangGraph Agent 适配器 - 实现 IAgentRunner 接口。
    
    将 Deep Agent 的流式输出转换为统一的 StreamEvent 格式。
    """
    
    def __init__(self, graph_factory: Any) -> None:
        """
        Args:
            graph_factory: 返回编译后 LangGraph 图的工厂函数
        """
        self._graph_factory = graph_factory
        self._graph = None
    
    def _ensure_graph(self) -> Any:
        """确保图已初始化。"""
        if self._graph is None:
            self._graph = self._graph_factory()
        return self._graph
    
    async def stream(
        self,
        session: Session,
        user_message: str,
        config: Optional[dict[str, Any]] = None,
    ) -> AsyncIterator[StreamEvent]:
        """流式执行 Agent 并产生事件。"""
        graph = self._ensure_graph()
        
        # 构建输入消息
        messages = self._session_to_messages(session)
        messages.append({"role": "user", "content": user_message})
        
        # 构建配置
        run_config = {
            "configurable": {
                "thread_id": str(session.id),
                "user_id": "default",  # TODO: 从上下文获取
                **(config or {}),
            }
        }
        
        msg_id = str(uuid4())
        
        # 发送消息开始事件
        yield StreamEvent(
            event=EventType.MESSAGE_START,
            data={"id": msg_id, "role": "assistant"},
        )
        
        current_thinking = ""
        current_content = ""
        in_thinking = False
        
        try:
            # 流式执行 Agent
            async for event in graph.astream_events(
                {"messages": messages},
                config=run_config,
                version="v2",
            ):
                event_type = event.get("event")
                
                # 处理 LLM 流式输出
                if event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = self._extract_content(chunk)
                        
                        # 检测思维链标签
                        if "<think>" in content:
                            in_thinking = True
                            yield StreamEvent(
                                event=EventType.THINKING_START,
                                data={"id": f"think_{msg_id}"},
                            )
                            content = content.replace("<think>", "")
                        
                        if "</think>" in content:
                            in_thinking = False
                            content = content.replace("</think>", "")
                            yield StreamEvent(
                                event=EventType.THINKING_END,
                                data={"id": f"think_{msg_id}"},
                            )
                        
                        if content:
                            if in_thinking:
                                current_thinking += content
                                yield StreamEvent(
                                    event=EventType.THINKING_DELTA,
                                    data={"delta": content},
                                )
                            else:
                                current_content += content
                                yield StreamEvent(
                                    event=EventType.CONTENT_DELTA,
                                    data={"delta": content},
                                )
                
                # 处理工具调用
                elif event_type == "on_tool_start":
                    tool_name = event.get("name", "unknown")
                    tool_input = event.get("data", {}).get("input", {})
                    yield StreamEvent(
                        event=EventType.TOOL_START,
                        data={"name": tool_name, "args": tool_input},
                    )
                
                elif event_type == "on_tool_end":
                    tool_name = event.get("name", "unknown")
                    tool_output = event.get("data", {}).get("output", "")
                    
                    # 检测图表数据
                    chart_data = self._extract_chart_data(tool_output)
                    if chart_data:
                        yield StreamEvent(
                            event=EventType.CHART,
                            data=chart_data,
                        )
                    
                    yield StreamEvent(
                        event=EventType.TOOL_RESULT,
                        data={"name": tool_name, "result": str(tool_output)[:500]},
                    )
            
            # 检查是否有 HITL 中断
            # TODO: 从 graph 状态获取中断信息
            
        except Exception as e:
            _LOGGER.exception("Agent execution error")
            yield StreamEvent(
                event=EventType.ERROR,
                data={"message": str(e)},
            )
        
        # 发送消息结束事件
        yield StreamEvent(
            event=EventType.MESSAGE_END,
            data={
                "id": msg_id,
                "content": current_content,
                "thinking": current_thinking if current_thinking else None,
            },
        )
    
    async def resume(
        self,
        session: Session,
        feedback: FeedbackRequest,
    ) -> AsyncIterator[StreamEvent]:
        """从 HITL 中断处恢复执行。"""
        graph = self._ensure_graph()
        
        # 构建恢复配置
        run_config = {
            "configurable": {
                "thread_id": str(session.id),
            }
        }
        
        msg_id = str(uuid4())
        
        yield StreamEvent(
            event=EventType.FEEDBACK_RECEIVED,
            data={"decision": feedback.decision, "message": feedback.message},
        )
        
        yield StreamEvent(
            event=EventType.MESSAGE_START,
            data={"id": msg_id, "role": "assistant"},
        )
        
        try:
            # 使用 Command.resume 恢复执行
            resume_value = {
                "decisions": [
                    {"type": feedback.decision, "message": feedback.message or ""}
                ]
            }
            
            async for event in graph.astream_events(
                None,  # 无新输入，从中断处恢复
                config={**run_config, "command": {"resume": resume_value}},
                version="v2",
            ):
                # 处理事件（与 stream 方法类似）
                event_type = event.get("event")
                if event_type == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk:
                        content = self._extract_content(chunk)
                        if content:
                            yield StreamEvent(
                                event=EventType.CONTENT_DELTA,
                                data={"delta": content},
                            )
        
        except Exception as e:
            _LOGGER.exception("Agent resume error")
            yield StreamEvent(
                event=EventType.ERROR,
                data={"message": str(e)},
            )
        
        yield StreamEvent(
            event=EventType.MESSAGE_END,
            data={"id": msg_id},
        )
    
    def _session_to_messages(self, session: Session) -> list[dict]:
        """将会话消息转换为 LangGraph 格式。"""
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in session.messages
        ]
    
    def _extract_content(self, chunk: Any) -> str:
        """从 LLM chunk 中提取文本内容。"""
        if hasattr(chunk, "content"):
            content = chunk.content
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        return block.get("text", "")
        return ""
    
    def _extract_chart_data(self, output: Any) -> Optional[dict]:
        """从工具输出中提取图表数据。"""
        if isinstance(output, str):
            # 检测 VISUALIZER_AGENT_COMPLETE 前缀
            if output.startswith("VISUALIZER_AGENT_COMPLETE:"):
                try:
                    import json
                    json_str = output[len("VISUALIZER_AGENT_COMPLETE:"):].strip()
                    parsed = json.loads(json_str)
                    chart_data = parsed.get("data", parsed)
                    return {
                        "type": "echarts",
                        "option": chart_data.get("option", chart_data),
                        "title": chart_data.get("title"),
                        "description": chart_data.get("description"),
                    }
                except Exception:
                    pass
        return None
