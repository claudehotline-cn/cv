"""Planner Sub-Agent Module"""
from __future__ import annotations

import logging
from deepagents import CompiledSubAgent
from langchain.agents import create_agent
from agent_core.runtime import build_chat_llm

from ..prompts import PLANNER_AGENT_PROMPT, PLANNER_AGENT_DESCRIPTION
from ..tools import generate_outline_tool

_LOGGER = logging.getLogger(__name__)

def get_planner_agent() -> CompiledSubAgent:
    """Create Planner Sub-Agent."""
    planner_llm = build_chat_llm(task_name="planner")
    planner_tools = [generate_outline_tool]
    
    # Force function calling for structured outline generation
    planner_llm_forced = planner_llm.bind_tools(
        planner_tools,
        tool_choice={"type": "function", "function": {"name": "generate_outline_tool"}}
    )
    
    planner_runnable = create_agent(
        model=planner_llm_forced,
        tools=planner_tools,
        system_prompt=PLANNER_AGENT_PROMPT,
    )
    
    return CompiledSubAgent(
        name="planner_agent",
        description=PLANNER_AGENT_DESCRIPTION,
        runnable=planner_runnable,
    )

planner_agent = get_planner_agent()
