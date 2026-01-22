"""Researcher Sub-Agent Module"""
from __future__ import annotations

import logging
from deepagents import CompiledSubAgent
from langchain.agents import create_agent
from agent_core.runtime import build_chat_llm

from ..prompts import RESEARCHER_AGENT_PROMPT, RESEARCHER_AGENT_DESCRIPTION
from ..tools import research_all_sections_tool

_LOGGER = logging.getLogger(__name__)

def get_researcher_agent() -> CompiledSubAgent:
    """Create Researcher Sub-Agent."""
    researcher_llm = build_chat_llm(task_name="researcher")
    researcher_tools = [research_all_sections_tool]
    
    # Force function calling for structured research execution
    researcher_llm_forced = researcher_llm.bind_tools(
        researcher_tools,
        tool_choice={"type": "function", "function": {"name": "research_all_sections_tool"}}
    )
    
    researcher_runnable = create_agent(
        model=researcher_llm_forced,
        tools=researcher_tools,
        system_prompt=RESEARCHER_AGENT_PROMPT,
    )
    
    return CompiledSubAgent(
        name="researcher_agent",
        description=RESEARCHER_AGENT_DESCRIPTION,
        runnable=researcher_runnable,
    )

researcher_agent = get_researcher_agent()
