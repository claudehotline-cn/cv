from typing import Any, Dict, List, Optional
import json
import logging
import os
import uuid
import re
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage, trim_messages
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime

_LOGGER = logging.getLogger(__name__)

import contextvars

_ANALYSIS_ID_CTX = contextvars.ContextVar("analysis_id", default=None)

class AnalysisIDMiddleware(AgentMiddleware):
    """Middleware to ensure analysis_id exists and is injected into tool calls."""
    
    def before_agent(self, state: AgentState, runtime: Runtime[Any]) -> Dict[str, Any] | None:
        """Check for analysis_id in user message."""
        messages = state.get("messages", [])
        
        # 1. Try to parse analysis_id from messages
        parsed_id = None
        for msg in reversed(messages):
            content = getattr(msg, "content", "")
            if isinstance(content, str):
                _LOGGER.debug(f"[AnalysisIDMiddleware] Scanning parsing content: {content[:100]}...")
                # Support [analysis_id=xxx], analysis_id=xxx, analysis_id: xxx
                match = re.search(r'\[?analysis_id[:\s=]+([a-zA-Z0-9_]+)\]?', content, re.IGNORECASE)
                if match:
                    parsed_id = match.group(1)
                    _LOGGER.info(f"[AnalysisIDMiddleware] Match found: {parsed_id}")
                    break
        
        # 2. Update ContextVar
        if parsed_id:
            _ANALYSIS_ID_CTX.set(parsed_id)
            _LOGGER.info(f"[AnalysisIDMiddleware] ✓ Set analysis_id: {parsed_id}")
        else:
            _LOGGER.warning(f"[AnalysisIDMiddleware] ✗ No analysis_id found in messages!")

        # 3. Ensure analysis_id is in state
        if "analysis_id" not in state and parsed_id:
            return {"analysis_id": parsed_id}
             
        return None
    

class ThinkingLoggerMiddleware(AgentMiddleware):
    """DeepSeek/Qwen Thinking Process Logger."""
    
    async def awrap_model_call(self, request, handler):
        response = await handler(request)
        try:
            messages = getattr(response, 'result', None)
            if not messages: return response
            
            for msg in messages:
                tool_calls = getattr(msg, 'tool_calls', None)
                if tool_calls:
                    _LOGGER.info(f"[LLM] Tool Calls: {len(tool_calls)}")
                
                additional_kwargs = getattr(msg, 'additional_kwargs', {})
                thinking = additional_kwargs.get('reasoning_content', '')
                if thinking:
                    _LOGGER.info(f"[THINKING] {len(thinking)} chars:\n{thinking[:500]}...")
        except Exception as e:
            _LOGGER.debug(f"ThinkingLogger error: {e}")
        return response

    def wrap_tool_call(self, request, handler):
        try:
            tool_call = getattr(request, 'tool_call', {})
            if isinstance(tool_call, dict):
                name = tool_call.get('name', 'unknown')
                args = tool_call.get('args', {})
            else:
                name = getattr(tool_call, 'name', 'unknown')
                args = getattr(tool_call, 'args', {})
            
            args_str = str(args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "...(truncated)"
                
            _LOGGER.info(f"[TOOL] Calling {name} args={args_str}")
        except Exception as e:
            _LOGGER.warning(f"[Middleware] Tool log error: {e}")
        return handler(request)

    async def awrap_tool_call(self, request, handler):
        """Async version of wrap_tool_call."""
        try:
            tool_call = getattr(request, 'tool_call', {})
            if isinstance(tool_call, dict):
                name = tool_call.get('name', 'unknown')
                args = tool_call.get('args', {})
            else:
                name = getattr(tool_call, 'name', 'unknown')
                args = getattr(tool_call, 'args', {})
                
            args_str = str(args)
            if len(args_str) > 500:
                args_str = args_str[:500] + "...(truncated)"
                
            _LOGGER.info(f"[TOOL] Calling {name} args={args_str}")
        except Exception as e:
            _LOGGER.warning(f"[Middleware] Tool log error: {e}")
        return await handler(request)

class StructuredOutputToTextMiddleware(AgentMiddleware):
    """Middleware to ensure structured output is returned as text in the final message."""
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        if "structured_response" in state and state["structured_response"]:
            structured_data = state["structured_response"]
            _LOGGER.info("Middleware: Found structured_response.")
            
            # ------------------------------------------------------------------
            # 从文件读取 Report Agent 生成的报告
            # ------------------------------------------------------------------
            try:
                analysis_id = state.get("analysis_id", "")
                report_content = ""
                
                if analysis_id:
                    report_path = f"/data/workspace/artifacts/data_analysis_{analysis_id}/report.md"
                    if os.path.exists(report_path):
                        with open(report_path, "r", encoding="utf-8") as f:
                            report_content = f.read()
                        _LOGGER.info("Middleware: Loaded report from file: %s (%d chars)", report_path, len(report_content))
                
                if report_content and hasattr(structured_data, "summary"):
                    structured_data.summary = report_content.strip()
            except Exception as e:
                _LOGGER.warning(f"Middleware: Failed to read report file: {e}")
            # ------------------------------------------------------------------

            try:
                if hasattr(structured_data, "model_dump_json"):
                    json_str = structured_data.model_dump_json()
                else:
                    json_str = json.dumps(structured_data, default=str, ensure_ascii=False)
                content = f"DATA_RESULT:{json_str}"
                return {"messages": [AIMessage(content=content)]}
            except Exception as e:
                _LOGGER.error("Middleware: Failed to serialize: %s", e)
        
        # Fallback: Check ToolMessages for hidden DATA_RESULT
        if "messages" in state:
            messages = state["messages"]
            last_msg = messages[-1] if messages else None
            structured_tool_output = None
            for msg in reversed(messages):
                if hasattr(msg, "content") and isinstance(msg.content, str):
                    if "DATA_RESULT:" in msg.content or "CHART_DATA:" in msg.content:
                         structured_tool_output = msg.content
                         break
            
            if structured_tool_output:
                if last_msg and isinstance(last_msg.content, str) and structured_tool_output not in last_msg.content:
                     _LOGGER.info("Middleware: Bubbling up hidden tool output.")
                     combined_content = f"{last_msg.content}\n\n{structured_tool_output}"
                     return {"messages": [AIMessage(content=combined_content)]}
        return None
