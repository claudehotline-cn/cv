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
    """将 Agent 的结构化输出序列化为 JSON 文本，供前端解析。
    
    职责：
    1. 从文件读取 Report Agent 生成的报告内容，覆盖到 structured_data.summary
    2. 从文件读取 Visualizer Agent 生成的图表配置，覆盖到 structured_data.chart
    3. 将 structured_data 序列化为 JSON，添加 DATA_RESULT: 前缀返回
    """
    
    def after_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        structured_data = state.get("structured_response")
        if not structured_data:
            return None
            
        _LOGGER.info("Middleware: Processing structured_response")
        
        # 尝试多种方式获取 analysis_id
        analysis_id = _ANALYSIS_ID_CTX.get() or state.get("analysis_id", "")
        
        # Fallback: 如果ContextVar和State都为空，再次尝试从消息中解析
        if not analysis_id:
            messages = state.get("messages", [])
            for msg in reversed(messages):
                content = getattr(msg, "content", "") if hasattr(msg, "content") else str(msg)
                match = re.search(r'\[?analysis_id[:\s=]+([a-zA-Z0-9_]+)\]?', str(content), re.IGNORECASE)
                if match:
                    analysis_id = match.group(1).strip()
                    _LOGGER.info("Middleware: Recovered analysis_id from messages: %s", analysis_id)
                    break
        
        artifact_dir = f"/data/workspace/artifacts/data_analysis_{analysis_id}" if analysis_id else ""
        
        _LOGGER.info("Middleware: Using analysis_id=%s, artifact_dir=%s", analysis_id, artifact_dir)
        
        # Step 1: 从文件读取报告内容
        if artifact_dir:
            report_path = os.path.join(artifact_dir, "report.md")
            try:
                if os.path.exists(report_path):
                    with open(report_path, "r", encoding="utf-8") as f:
                        report_content = f.read().strip()
                    if report_content and hasattr(structured_data, "summary"):
                        structured_data.summary = report_content
                        _LOGGER.info("Middleware: Loaded report (%d chars)", len(report_content))
            except Exception as e:
                _LOGGER.warning("Middleware: Failed to read report: %s", e)
        
        # Step 2: 从文件读取图表配置
        if artifact_dir:
            chart_path = os.path.join(artifact_dir, "chart.json")
            try:
                if os.path.exists(chart_path):
                    with open(chart_path, "r", encoding="utf-8") as f:
                        chart_content = f.read().strip()
                    if chart_content and hasattr(structured_data, "chart"):
                        # 解析 JSON 并赋值（保留完整结构，包含 success/chart_type/option，防止前端依赖 success 字段 check）
                        structured_data.chart = json.loads(chart_content)
                        _LOGGER.info("Middleware: Loaded chart (%d chars)", len(chart_content))
            except Exception as e:
                _LOGGER.warning("Middleware: Failed to read chart: %s", e)
        
        # Step 3: 序列化并返回
        try:
            if hasattr(structured_data, "model_dump_json"):
                json_str = structured_data.model_dump_json()
            else:
                json_str = json.dumps(structured_data, default=str, ensure_ascii=False)
            
            return {"messages": [AIMessage(content=f"DATA_RESULT:{json_str}")]}
        except Exception as e:
            _LOGGER.error("Middleware: Failed to serialize: %s", e)
            return None
