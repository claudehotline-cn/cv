from typing import Any, Dict, List, Optional
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
        description: str = "Please confirm to proceed"
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
                
                interrupt_value = {
                    "action_requests": [{
                        "name": subagent_type,
                        "args": args,
                        "description": f"{self.description}\n\n{subagent_type} completed."
                    }],
                    "review_configs": [{
                        "action_name": subagent_type,
                        "allowed_decisions": self.allowed_decisions
                    }]
                }
                
                interrupt_res = interrupt(interrupt_value)
                
                if isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                    decisions = interrupt_res["decisions"]
                    if decisions and isinstance(decisions, list):
                        decision = decisions[0]
                        if decision.get("type") == "reject":
                            feedback = decision.get("message", f"User rejected {subagent_type}")
                            return f"USER_INTERRUPT: {feedback}"

                if subagent_type == "visualizer_agent":
                    return f"USER_APPROVED: Chart approved."
                elif subagent_type == "report_agent":
                    return f"USER_APPROVED: Report approved."
                else:
                    return f"USER_APPROVED: {subagent_type} approved."
        
        return await handler(request)
