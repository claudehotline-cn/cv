from typing import Any, Dict, List, Optional, Union
import json
import logging
import os
import uuid
import re
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage, ToolMessage, trim_messages
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from deepagents.backends import StoreBackend


_LOGGER = logging.getLogger(__name__)


class SubAgentHITLMiddleware(AgentMiddleware):
    """
    Custom HITL Middleware for SubAgent Interruption.
    """
    
    def __init__(
        self, 
        interrupt_subagents: List[str] = None,
        allowed_decisions: List[str] = None,
        description: Union[str, Dict[str, str]] = "Please confirm to proceed"
    ):
        super().__init__()
        self.interrupt_subagents = interrupt_subagents or ["visualizer_agent", "report_agent"]
        self.allowed_decisions = allowed_decisions or ["approve", "reject"]
        self.description = description
    
    async def awrap_tool_call(self, request, handler):
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            args = tool_call.get('args', {})
        else:
            tool_name = getattr(tool_call, 'name', '')
            args = getattr(tool_call, 'args', {})
        
        _LOGGER.info(f"[HITL DEBUG] awrap_tool_call: {tool_name}")
        
        if tool_name == 'task':
            subagent_type = args.get('subagent_type', '')
            
            if subagent_type in self.interrupt_subagents:
                _LOGGER.info(f"[HITL] Executing {subagent_type} first, will interrupt after completion")
                
                response = await handler(request)
                
                # Extract content for preview
                preview_content = None
                if isinstance(response, str):
                    preview_content = response
                elif hasattr(response, 'update') and isinstance(response.update, dict):
                    # Handle Command object
                    msgs = response.update.get("messages", [])
                    if msgs:
                        last_msg = msgs[-1]
                        if isinstance(last_msg, ToolMessage):
                            preview_content = last_msg.content
                        elif hasattr(last_msg, 'content'):
                            preview_content = last_msg.content
                
                # Determine description based on subagent_type
                if isinstance(self.description, dict):
                    desc = self.description.get(subagent_type, self.description.get("default", "操作完成，请确认是否继续"))
                else:
                    desc = self.description

                interrupt_value = {
                    "action_requests": [{
                        "name": subagent_type,
                        "args": args,
                        "description": desc
                    }],
                    "review_configs": [{
                        "action_name": subagent_type,
                        "allowed_decisions": self.allowed_decisions
                    }],
                    "preview": preview_content
                }
                
                interrupt_res = interrupt(interrupt_value)
                
                # Get tool_call_id for ToolMessage
                tool_call_id = tool_call.get('id', '') if isinstance(tool_call, dict) else getattr(tool_call, 'id', '')
                
                _LOGGER.info(f"[HITL] interrupt_res type: {type(interrupt_res)}, value: {interrupt_res}")
                
                # interrupt() returns the exact value passed to Command(resume=...)
                # Backend passes: [{"type": "approve"|"reject", "message": "..."}]
                decisions = None
                if isinstance(interrupt_res, list):
                    decisions = interrupt_res
                elif isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                    decisions = interrupt_res["decisions"]
                
                if decisions and isinstance(decisions, list) and len(decisions) > 0:
                    decision = decisions[0]
                    if decision.get("type") == "reject":
                        feedback = decision.get("message", "")
                        content = f"USER_INTERRUPT: 用户拒绝了 {subagent_type} 的输出。反馈: {feedback}。请根据反馈重新调用 {subagent_type}。"
                        _LOGGER.info(f"[HITL] User rejected, returning: {content}")
                        return ToolMessage(content=content, tool_call_id=tool_call_id)

                # Generic approval message with subagent_type
                content = f"USER_APPROVED: {subagent_type} approved."
                _LOGGER.info(f"[HITL] User approved or no decision, returning: {content}")
                
                return ToolMessage(content=content, tool_call_id=tool_call_id)
        
        return await handler(request)
