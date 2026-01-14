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
                
                # Try to extract thinking from content_blocks (Standard LangChain)
                thinking = ""
                content_blocks = getattr(msg, 'content_blocks', [])
                for block in content_blocks:
                    if isinstance(block, dict) and block.get('type') == 'reasoning':
                        thinking += block.get('reasoning', '')
                
                # Fallback to additional_kwargs (Legacy/Provider specific)
                if not thinking:
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

class FileContentInjectionMiddleware(AgentMiddleware):
    """
    Middleware 拦截 'task' 工具调用，检测 Visualizer/Report Agent，
    读取它们生成的 'chart.json' 或 'report.md'，并注入到 ToolMessage.artifact 中。
    这允许前端直接接收结构化数据进行渲染，而无需等待主 Agent 冒泡结果。
    """

    async def awrap_tool_call(self, request, handler):
        # 1. 执行原工具调用，获取基础回复 (subagent 运行结果 ToolMessage or str)
        response = await handler(request)
        
        # 2. 检查是否是目标 subagent
        try:
            tool_call = getattr(request, 'tool_call', {})
            # Normalized tool access
            if isinstance(tool_call, dict):
                tool_name = tool_call.get('name', '')
                args = tool_call.get('args', {})
                tool_id = tool_call.get('id', '')
            else:
                tool_name = getattr(tool_call, 'name', '')
                args = getattr(tool_call, 'args', {})
                tool_id = getattr(tool_call, 'id', '')

            subagent = args.get('subagent_type')
        except Exception:
            # Fallback safe
            tool_name = ""
            subagent = ""

        if tool_name == 'task' and subagent in ['visualizer_agent', 'report_agent']:
            # 获取 ID (复用通用的从 context/config 获取逻辑)
            runtime = getattr(request, 'runtime', None)
            analysis_id, user_id = "", "anonymous"
            if runtime:
                # 1. context (CLI)
                if hasattr(runtime, 'context') and isinstance(runtime.context, dict):
                    analysis_id = runtime.context.get("analysis_id", "")
                    user_id = runtime.context.get("user_id", "anonymous")
                
                # 2. config (Fallback)
                if not analysis_id:
                    config = getattr(runtime, "config", {})
                    configurable = config.get("configurable", {})
                    analysis_id = configurable.get("analysis_id", "")
                    if user_id == "anonymous":
                        user_id = configurable.get("user_id", "anonymous")

            if analysis_id:
                artifact_dir = f"/data/workspace/{user_id}/artifacts/data_analysis_{analysis_id}"
                injected_artifact = {}
                inject_msg = ""

                try:
                    if subagent == 'visualizer_agent':
                        # 读取 chart.json
                        chart_path = os.path.join(artifact_dir, "chart.json")
                        if os.path.exists(chart_path):
                            with open(chart_path, "r", encoding="utf-8") as f:
                                chart_content = f.read().strip()
                            if chart_content:
                                chart_data = json.loads(chart_content)
                                injected_artifact = {"type": "chart", "data": chart_data}
                                inject_msg = f"\n\n[SYSTEM] Successfully loaded chart.json ({len(chart_content)} chars)."
                                _LOGGER.info(f"[Middleware] Injected chart artifact for {analysis_id}")
                    
                    elif subagent == 'report_agent':
                        # 读取 report.md
                        report_path = os.path.join(artifact_dir, "report.md")
                        if os.path.exists(report_path):
                            with open(report_path, "r", encoding="utf-8") as f:
                                report_content = f.read().strip()
                            if report_content:
                                injected_artifact = {"type": "report", "content": report_content}
                                inject_msg = f"\n\n[SYSTEM] Successfully loaded report.md ({len(report_content)} chars)."
                                _LOGGER.info(f"[Middleware] Injected report artifact for {analysis_id}")

                except Exception as e:
                    _LOGGER.warning(f"[Middleware] Failed to read artifact: {e}")

                if injected_artifact:
                    # 3. 构造 ToolMessage (带 artifact)
                    # response 可能是 str 或 AIMessage/ToolMessage。这里我们作为 Tool 的结果返回，必须也是 Message。
                    # LangGraph 的 handler 一般返回 Message 或 content list。我们用 ToolMessage 包装最为稳妥。
                    
                    # 确定 content: 如果 response 是对象，取其 content；如果是 str，直接用
                    original_content = ""
                    if hasattr(response, 'content'):
                        original_content = response.content
                    else:
                        original_content = str(response)

                    new_content = original_content + inject_msg

                    return ToolMessage(
                        tool_call_id=tool_id,
                        content=new_content,     # LLM 看到的 (带提示)
                        artifact=injected_artifact, # 前端看到的结构化数据
                        name=tool_name,
                        status="success"
                    )

        return response


class SubAgentHITLMiddleware(AgentMiddleware):
    """
    自定义 Human-in-the-Loop 中间件，在特定 SubAgent 调用之前触发中断。
    
    由于所有 SubAgent 都通过 'task' 工具调用，标准 HumanInTheLoopMiddleware
    无法按 subagent_type 参数过滤。此中间件解决这个问题。
    
    配置:
        interrupt_subagents: 需要中断的 subagent 名称列表
        allowed_decisions: 允许的决策类型
    """
    
    def __init__(
        self, 
        interrupt_subagents: List[str] = None,
        allowed_decisions: List[str] = None,
        description: str = "请确认是否继续"
    ):
        super().__init__()
        self.interrupt_subagents = interrupt_subagents or ["report_agent"]
        self.allowed_decisions = allowed_decisions or ["approve", "reject"]
        self.description = description
    
    async def awrap_tool_call(self, request, handler):
        """在工具调用之前检查是否需要中断。"""
        tool_call = getattr(request, 'tool_call', {})
        if isinstance(tool_call, dict):
            tool_name = tool_call.get('name', '')
            args = tool_call.get('args', {})
        else:
            tool_name = getattr(tool_call, 'name', '')
            args = getattr(tool_call, 'args', {})
        
        # DEBUG: Log every tool call to see what's coming through
        _LOGGER.info(f"[HITL DEBUG] awrap_tool_call invoked: tool_name='{tool_name}', args_keys={list(args.keys()) if isinstance(args, dict) else type(args)}")
        
        # 只处理 task 工具
        if tool_name == 'task':
            subagent_type = args.get('subagent_type', '')
            
            # 检查是否是需要中断的 subagent
            if subagent_type in self.interrupt_subagents:
                _LOGGER.info(f"[HITL] Triggering interrupt before calling {subagent_type}")
                
                # 构造中断请求
                interrupt_value = {
                    "action_requests": [{
                        "name": subagent_type,
                        "args": args,
                        "description": f"{self.description}\n\n即将调用: {subagent_type}"
                    }],
                    "review_configs": [{
                        "action_name": subagent_type,
                        "allowed_decisions": self.allowed_decisions
                    }]
                }
                
                # 触发中断，等待用户决策
                # interrupt() 会抛出 GraphInterrupt 异常，必须让它向上传播
                interrupt_res = interrupt(interrupt_value)
                
                # 如果代码继续执行到这里，说明用户已恢复
                _LOGGER.info(f"[HITL] Resumed with: {interrupt_res}")
                
                # 检查用户的决定
                if isinstance(interrupt_res, dict) and "decisions" in interrupt_res:
                    decisions = interrupt_res["decisions"]
                    if decisions and isinstance(decisions, list):
                        decision = decisions[0]
                        if decision.get("type") == "reject":
                            feedback = decision.get("message", "用户拒绝了执行")
                            _LOGGER.info(f"[HITL] User rejected {subagent_type}: {feedback}")
                            
                            # 返回用户反馈作为工具执行结果，而不是执行 handler
                            # 这将告诉 Agent 这一步失败了（或者完成了但有反馈），Agent 应该根据反馈进行调整
                            return f"USER_INTERRUPT: 用户拒绝了执行 {subagent_type}。原因: {feedback}。请根据此反馈修改之前的步骤或数据。"

                _LOGGER.info(f"[HITL] User approved, continuing with {subagent_type}")
        
        # 继续执行工具调用
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
        # Priority 1: Check runtime.context (Propagated from request config)
        analysis_id = ""
        user_id = "anonymous"
        
        if hasattr(runtime, 'context') and isinstance(runtime.context, dict):
            analysis_id = runtime.context.get("analysis_id", "")
            user_id = runtime.context.get("user_id", "anonymous")

        # Priority 2: Check config.configurable (Fallback)
        if not analysis_id:
            config = getattr(runtime, "config", {})
            configurable = config.get("configurable", {})
            analysis_id = configurable.get("analysis_id", "")
            if not user_id or user_id == "anonymous":
                user_id = configurable.get("user_id", "anonymous")

        # Priority 3: Check state (Legacy support)
        if not analysis_id:
            analysis_id = state.get("analysis_id", "")
        
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
