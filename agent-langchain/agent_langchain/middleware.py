from typing import Any, Dict, List, Optional
import json
import logging
import os
import uuid
import re
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, HumanMessage, trim_messages
from langchain.agents.middleware.types import AgentMiddleware, AgentState
from langgraph.runtime import Runtime
from deepagents.backends import StoreBackend
import contextvars

_LOGGER = logging.getLogger(__name__)

# ContextVar to pass user_id between middlewares within the same request context
_USER_ID_CONTEXT = contextvars.ContextVar("user_id", default="")

# 使用 runtime.store (LangGraph BaseStore) 存储 analysis_id
# 通过 deepagents 的 StoreBackend 实现跨线程持久化

# Namespace 用于 Store 中的 analysis_id 存储
_ANALYSIS_ID_NAMESPACE = ("analysis",)

class AnalysisIDMiddleware(AgentMiddleware):
    """Middleware to ensure analysis_id exists and is injected into tool calls."""
    
    async def abefore_agent(self, state: AgentState, runtime: Runtime[Any]) -> Dict[str, Any] | None:
        """Check for analysis_id in user message (async version)."""
        _LOGGER.info("[AnalysisIDMiddleware] abefore_agent called, store=%s", "available" if runtime.store else "None")
        messages = state.get("messages", [])
        
        # 1. Try to parse analysis_id from messages
        parsed_id = None
        for msg in reversed(messages):
            content = getattr(msg, "content", "")
            
            # Normalize content to string for regex search
            text_to_search = ""
            if isinstance(content, str):
                text_to_search = content
            elif isinstance(content, list):
                # Handle Content Blocks: extract text from {"type": "text", "text": "..."}
                for block in content:
                    if isinstance(block, dict) and block.get("type") == "text":
                        text_to_search += block.get("text", "") + "\n"
            
            if text_to_search:
                _LOGGER.debug(f"[AnalysisIDMiddleware] Scanning parsing content: {text_to_search[:100]}...")
                # Support [analysis_id=xxx], analysis_id=xxx, analysis_id: xxx
                match = re.search(r'\[?analysis_id[:\s=]+([a-zA-Z0-9_]+)\]?', text_to_search, re.IGNORECASE)
                if match:
                    parsed_id = match.group(1)
                    _LOGGER.info(f"[AnalysisIDMiddleware] Match found: {parsed_id}")
                    break
        
        # 2. Store in LangGraph Store (via runtime.store) - using async API
        if parsed_id:
            try:
                # Use StoreBackend to write to the /_shared/ route for isolation and persistence
                sb = StoreBackend(runtime)
                await sb.awrite("/_shared/analysis_id", parsed_id)
                _LOGGER.info(f"[AnalysisIDMiddleware] ✓ Persisted analysis_id={parsed_id} to /_shared/analysis_id")
            except Exception as e:
                _LOGGER.warning(f"[AnalysisIDMiddleware] Failed to persist to StoreBackend: {e}")
        else:
            _LOGGER.warning(f"[AnalysisIDMiddleware] ✗ No analysis_id found in messages!")

        # 3. Ensure analysis_id is in state
        if "analysis_id" not in state and parsed_id:
            return {"analysis_id": parsed_id}
             
        return None

class UserIdInjectionMiddleware(AgentMiddleware):
    """
    Middleware to inject user_id into tool calls.
    This ensures Sub-Agents receive user_id when called by the Main Agent.
    """
    MOCK_USER_ID = "mock_user_from_tool_call_999"  # For testing
    
    # Only inject into Sub-Agent Task Tools
    SUBAGENT_TOOLS = {"sql_agent", "python_agent", "excel_agent", "visualizer_agent", "reviewer_agent", "report_agent"}
    
    async def abefore_agent(self, state: AgentState, runtime: Runtime[Any]) -> Dict[str, Any] | None:
        """Inject mock_user_id into Main Agent state."""
        # Inject user_id if not present in state or empty, OR if it is "anonymous" (default placeholder)
        current_user_id = state.get("user_id")
        if not current_user_id or current_user_id == "anonymous":
            _LOGGER.info(f"[UserIdInjectionMiddleware] Injecting user_id={self.MOCK_USER_ID} into Main Agent state/config")
            
            # Inject directly into runtime.config so downstream middleware can read it
            if hasattr(runtime, 'config'):
                if 'configurable' not in runtime.config:
                    runtime.config['configurable'] = {}
                runtime.config['configurable']['user_id'] = self.MOCK_USER_ID

            # Set ContextVar for internal middleware communication
            _USER_ID_CONTEXT.set(self.MOCK_USER_ID)
            
            return {"user_id": self.MOCK_USER_ID}
        return None

    async def awrap_tool_call(self, request, handler):
        # tool_call is a dict, not an object
        tool_call = request.tool_call
        tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
        args = tool_call.get('args', {}) if isinstance(tool_call, dict) else {}
        
        # Only process 'task' tool (which calls Sub-Agents)
        if tool_name == 'task':
            subagent_type = args.get('subagent_type', '')
            if subagent_type in self.SUBAGENT_TOOLS:
                tool_runtime = request.runtime
                # Inject user_id into ToolRuntime.config
                if hasattr(tool_runtime, 'config') and tool_runtime.config:
                    configurable = tool_runtime.config.get('configurable', {})
                    user_id = configurable.get('user_id')
                    
                    if not user_id:  # Handles None or empty string
                        configurable['user_id'] = self.MOCK_USER_ID
                        tool_runtime.config['configurable'] = configurable
                        _LOGGER.info(f"[UserIdInjectionMiddleware] Injected user_id={self.MOCK_USER_ID} into ToolRuntime.config for subagent '{subagent_type}' (was '{user_id}')")
                    else:
                        _LOGGER.debug(f"[UserIdInjectionMiddleware] user_id already present: {user_id}")
        
        # Call the original handler
        return await handler(request)
    

class ThinkingLoggerMiddleware(AgentMiddleware):
    """DeepSeek/Qwen Thinking Process Logger."""
    
    async def awrap_model_call(self, request, handler):
        # DEBUG: Log request message structure before LLM call (using content_blocks)
        try:
            req_messages = getattr(request, 'messages', [])
            _LOGGER.info(f"[MIDDLEWARE DEBUG] awrap_model_call: {len(req_messages)} messages")
            for i, m in enumerate(req_messages[-5:]):  # Log last 5 messages
                blocks = getattr(m, 'content_blocks', [])
                _LOGGER.info(f"[MIDDLEWARE DEBUG] Msg[{i}] role={type(m).__name__}, content_blocks_count={len(blocks)}")
        except Exception as e:
            _LOGGER.debug(f"[MIDDLEWARE DEBUG] Log error: {e}")
        
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
    
    async def aafter_agent(self, state: AgentState, runtime: Runtime[Any], result: Any = None) -> Dict[str, Any] | None:
        structured_data = state.get("structured_response")
        if not structured_data:
            return None
            
        _LOGGER.info("Middleware: Processing structured_response")
        
        # 尝试多种方式获取 analysis_id
        thread_id = state.get("configurable", {}).get("thread_id", "default")
        analysis_id = state.get("analysis_id", "")
        
        # 尝试从 Store 获取 (使用异步 API)
        if not analysis_id and runtime.store is not None:
            try:
                item = await runtime.store.aget(namespace=_ANALYSIS_ID_NAMESPACE, key=thread_id)
                if item and isinstance(item.value, dict):
                    analysis_id = item.value.get("analysis_id", "")
                    _LOGGER.info(f"Middleware: Retrieved analysis_id={analysis_id} from Store")
            except Exception as e:
                _LOGGER.debug(f"Middleware: Failed to get analysis_id from Store: {e}")
        
        # 如果仍然没有 analysis_id，记录警告\n        if not analysis_id:\n            _LOGGER.warning(\"Middleware: No analysis_id found in state or Store\")
        
        # Extract user_id from runtime.config for path isolation
        user_id = "anonymous"
        
        # Priority 1: Check runtime config (Standard way)
        if hasattr(runtime, 'config') and runtime.config:
            _LOGGER.info(f"[DEBUG] runtime.config.configurable = {runtime.config.get('configurable', {})}")
            cfg_user_id = runtime.config.get("configurable", {}).get("user_id", "")
            if cfg_user_id:
                user_id = cfg_user_id
        
        # Priority 2: Check state (Fallback)
        if user_id == "anonymous":
             state_user_id = state.get("configurable", {}).get("user_id", "")
             if state_user_id:
                 user_id = state_user_id

        # Priority 3: Check ContextVar (Reliable internal fallback)
        if user_id == "anonymous":
             ctx_user_id = _USER_ID_CONTEXT.get()
             if ctx_user_id:
                 user_id = ctx_user_id
                 _LOGGER.info(f"Middleware: Retrieved user_id={user_id} from ContextVar")
        
        artifact_dir = f"/data/workspace/{user_id}/artifacts/data_analysis_{analysis_id}" if analysis_id else ""
        
        _LOGGER.info("Middleware: Using analysis_id=%s, user_id=%s, artifact_dir=%s", analysis_id, user_id, artifact_dir)
        
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
            _LOGGER.info("Middleware: Checking chart path: %s", chart_path)
            try:
                if os.path.exists(chart_path):
                    with open(chart_path, "r", encoding="utf-8") as f:
                        chart_content = f.read().strip()
                    
                    has_chart_attr = hasattr(structured_data, "chart")
                    _LOGGER.info("Middleware: Chart content len=%d, has_chart_attr=%s", len(chart_content), has_chart_attr)
                    
                    if chart_content and has_chart_attr:
                        # 解析 JSON 并赋值（保留完整结构，包含 success/chart_type/option，防止前端依赖 success 字段 check）
                        chart_json = json.loads(chart_content)
                        structured_data.chart = chart_json
                        _LOGGER.info("Middleware: Loaded chart success. Keys: %s", list(chart_json.keys()) if isinstance(chart_json, dict) else "NotDict")
                    else:
                        _LOGGER.warning("Middleware: Skipped chart assignment. Content empty or no attr.")
                else:
                    _LOGGER.info("Middleware: Chart file not found.")
            except Exception as e:
                _LOGGER.warning("Middleware: Failed to read chart: %s", e)
        
        # Step 3: 序列化并返回
        try:
            if hasattr(structured_data, "model_dump_json"):
                json_str = structured_data.model_dump_json()
            else:
                json_str = json.dumps(structured_data, default=str, ensure_ascii=False)
            
            # Debug log to verify chart field presence in final output
            has_chart = '"chart":' in json_str
            _LOGGER.info("Middleware: Serialized JSON (len=%d), has_chart=%s", len(json_str), has_chart)
            
            # User requested full log without truncation
            _LOGGER.info("Middleware: FINAL_FULL_JSON_PAYLOAD:\n%s", json_str)
            
            return {"messages": [AIMessage(content=f"DATA_RESULT:{json_str}")]}
        except Exception as e:
            _LOGGER.error("Middleware: Failed to serialize: %s", e)
            return None
