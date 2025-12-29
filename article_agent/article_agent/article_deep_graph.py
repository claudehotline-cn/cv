"""Article Deep Agent (Multi-Agent Version)：基于 deepagents 实现的分层多智能体文章生成系统。"""

from __future__ import annotations

import logging
from typing import Any

from deepagents import create_deep_agent, SubAgent

from .llm_runtime import build_chat_llm
from .article_deep_prompts import (
    MAIN_AGENT_PROMPT,
    COLLECTOR_AGENT_PROMPT,
    COLLECTOR_AGENT_DESCRIPTION,
    PLANNER_AGENT_PROMPT,
    PLANNER_AGENT_DESCRIPTION,
    RESEARCHER_AGENT_PROMPT,
    RESEARCHER_AGENT_DESCRIPTION,
    WRITER_AGENT_PROMPT,
    WRITER_AGENT_DESCRIPTION,
    REVIEWER_AGENT_PROMPT,
    REVIEWER_AGENT_DESCRIPTION,
    ILLUSTRATOR_AGENT_PROMPT,
    ILLUSTRATOR_AGENT_DESCRIPTION,
    ASSEMBLER_AGENT_PROMPT,
    ASSEMBLER_AGENT_DESCRIPTION,
)
from .article_deep_schemas import ArticleAgentOutput
from .article_deep_tools import (
    # Collector tools
    fetch_url_tool,
    load_file_tool,
    collect_all_sources_tool,
    # Planner tools
    generate_outline_tool,
    # Researcher tools
    read_sources_tool,
    research_section_tool,
    research_all_sections_tool,
    research_audit_tool,
    # Writer tools
    write_section_tool,
    write_all_sections_tool,
    writer_audit_tool,
    # Reviewer tools
    review_draft_tool,
    # Illustrator tools
    match_images_tool,
    # Assembler tools
    assemble_article_tool,
)

_LOGGER = logging.getLogger("article_agent.article_deep_graph")



def get_article_deep_agent_graph() -> Any:
    """构造并返回 Article Deep Agent (Multi-Agent 架构)。
    
    入口函数，被 langgraph.json 引用。
    """
    from langchain.agents.middleware import AgentMiddleware
    
    class ThinkingLoggerMiddleware(AgentMiddleware):
        """自定义 middleware 用于记录 Main Agent 的思维链内容。"""
        
        async def awrap_model_call(self, request, handler):
            """异步包装模型调用，记录思维内容和工具调用诊断。"""
            # 执行原始模型调用
            response = await handler(request)
            
            # 提取并记录思维内容
            try:
                # ModelResponse.result 是 list[BaseMessage]
                # 直接从消息中提取 reasoning_content
                messages = getattr(response, 'result', None)
                if not messages:
                    _LOGGER.warning("[LLM_RESPONSE] No messages in response!")
                    return response
                
                for msg in messages:
                    # 诊断日志：检查 tool_calls 是否存在
                    tool_calls = getattr(msg, 'tool_calls', None)
                    content = getattr(msg, 'content', '')
                    content_preview = content[:200] if content else "(empty)"
                    
                    if tool_calls:
                        _LOGGER.info(
                            "[LLM_RESPONSE] tool_calls PRESENT, count=%d, names=%s",
                            len(tool_calls),
                            [tc.get('name', 'unknown') if isinstance(tc, dict) else getattr(tc, 'name', 'unknown') for tc in tool_calls]
                        )
                    else:
                        _LOGGER.warning(
                            "[LLM_RESPONSE] tool_calls MISSING! content_preview: %s",
                            content_preview
                        )
                    
                    # 记录思维链内容
                    additional_kwargs = getattr(msg, 'additional_kwargs', {})
                    thinking_content = additional_kwargs.get('reasoning_content', '')
                    if thinking_content:
                        thinking_preview = thinking_content[:2000]
                        if len(thinking_content) > 2000:
                            thinking_preview += "..."
                        _LOGGER.info(
                            "[CHAIN_OF_THOUGHT] main_agent thinking_len=%d:\n"
                            "--- THINKING START ---\n%s\n--- THINKING END ---",
                            len(thinking_content), thinking_preview
                        )
            except Exception as e:
                _LOGGER.debug("ThinkingLoggerMiddleware.awrap_model_call error: %s", e)
            
            return response
        
        def wrap_tool_call(self, request, handler):
            """同步包装工具调用，记录 tool 调用参数。"""
            try:
                tool_call = getattr(request, 'tool_call', {})
                tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
                tool_args = tool_call.get('args', {}) if isinstance(tool_call, dict) else getattr(tool_call, 'args', {})
                # 截断长参数以避免日志爆炸
                args_preview = str(tool_args)[:1000]
                if len(str(tool_args)) > 1000:
                    args_preview += "..."
                _LOGGER.info(
                    "[TOOL_CALL] Main Agent calling tool: %s\nArgs: %s",
                    tool_name, args_preview
                )
            except Exception as e:
                _LOGGER.debug("ThinkingLoggerMiddleware.wrap_tool_call logging error: %s", e)
            return handler(request)

        
        async def awrap_tool_call(self, request, handler):
            """异步包装工具调用，记录 tool 调用参数。"""
            try:
                tool_call = getattr(request, 'tool_call', {})
                tool_name = tool_call.get('name', 'unknown') if isinstance(tool_call, dict) else getattr(tool_call, 'name', 'unknown')
                tool_args = tool_call.get('args', {}) if isinstance(tool_call, dict) else getattr(tool_call, 'args', {})
                # 截断长参数以避免日志爆炸
                args_preview = str(tool_args)[:1000]
                if len(str(tool_args)) > 1000:
                    args_preview += "..."
                _LOGGER.info(
                    "[TOOL_CALL] Main Agent calling tool: %s\nArgs: %s",
                    tool_name, args_preview
                )
            except Exception as e:
                _LOGGER.debug("ThinkingLoggerMiddleware.awrap_tool_call logging error: %s", e)
            return await handler(request)
    
    # 创建思维链日志 middleware
    thinking_middleware = ThinkingLoggerMiddleware()
    
    # 使用配置的 LLM
    # 恢复推理模式 - 禁用推理会导致工具调用生成失败
    main_llm = build_chat_llm(task_name="article_deep_main", enable_reasoning=True)
    
    # ============================================================================
    # 定义子 Agent (Sub-Agents)
    # ============================================================================
    
    # 1. Planner Agent - 素材收集 + 大纲规划（合并 collector 功能）
    planner_agent = SubAgent(
        name="planner_agent",
        description=PLANNER_AGENT_DESCRIPTION,
        system_prompt=PLANNER_AGENT_PROMPT,
        tools=[fetch_url_tool, load_file_tool, collect_all_sources_tool, generate_outline_tool],
    )
    
    # 2. Researcher Agent - 资料整理
    researcher_agent = SubAgent(
        name="researcher_agent",
        description=RESEARCHER_AGENT_DESCRIPTION,
        system_prompt=RESEARCHER_AGENT_PROMPT,
        tools=[read_sources_tool, research_section_tool, research_all_sections_tool, research_audit_tool],
    )
    
    # 4. Writer Agent - 内容撰写
    writer_agent = SubAgent(
        name="writer_agent",
        description=WRITER_AGENT_DESCRIPTION,
        system_prompt=WRITER_AGENT_PROMPT,
        tools=[write_section_tool, write_all_sections_tool, writer_audit_tool],
    )
    
    # 5. Reviewer Agent - 质量审阅
    reviewer_agent = SubAgent(
        name="reviewer_agent",
        description=REVIEWER_AGENT_DESCRIPTION,
        system_prompt=REVIEWER_AGENT_PROMPT,
        tools=[review_draft_tool],
    )
    
    # 6. Illustrator Agent - 智能配图
    illustrator_agent = SubAgent(
        name="illustrator_agent",
        description=ILLUSTRATOR_AGENT_DESCRIPTION,
        system_prompt=ILLUSTRATOR_AGENT_PROMPT,
        tools=[match_images_tool],
    )
    
    # 7. Assembler Agent - 组装输出
    assembler_agent = SubAgent(
        name="assembler_agent",
        description=ASSEMBLER_AGENT_DESCRIPTION,
        system_prompt=ASSEMBLER_AGENT_PROMPT,
        tools=[assemble_article_tool],
    )
    
    # ============================================================================
    # 创建主 Deep Agent
    # ============================================================================
    
    # 配置结构化输出 
    # 注意：暂时禁用 response_format，让 Main Agent 自由执行 SubAgents
    # try:
    #     from langchain.agents.structured_output import ToolStrategy
    #     response_format = ToolStrategy(ArticleAgentOutput)
    # except ImportError:
    #     response_format = ArticleAgentOutput
    
    # 创建 Deep Agent
    graph = create_deep_agent(
        model=main_llm,
        subagents=[
            planner_agent,  # 包含素材收集 + 大纲规划
            researcher_agent,
            writer_agent,
            reviewer_agent,
            illustrator_agent,
            assembler_agent,
        ],
        tools=[],  # Main Agent 不直接使用工具，通过 SubAgents 执行
        system_prompt=MAIN_AGENT_PROMPT,
        middleware=[thinking_middleware],  # 添加思维链日志 middleware
        # response_format=response_format,  # 暂时禁用，让 Agent 自由执行
    )
    
    _LOGGER.info("Article Deep Agent graph created with 6 SubAgents")
    
    return graph


__all__ = ["get_article_deep_agent_graph"]
