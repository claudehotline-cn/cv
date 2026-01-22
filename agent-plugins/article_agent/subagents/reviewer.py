"""Reviewer Sub-Agent Module"""
from __future__ import annotations

import logging
from deepagents import CompiledSubAgent
from langchain.agents import create_agent
from agent_core.runtime import build_chat_llm

from ..prompts import REVIEWER_AGENT_PROMPT, REVIEWER_AGENT_DESCRIPTION
from ..tools import review_draft_tool

_LOGGER = logging.getLogger(__name__)

def get_reviewer_agent() -> CompiledSubAgent:
    """Create Reviewer Sub-Agent."""
    reviewer_llm = build_chat_llm(task_name="reviewer")
    reviewer_tools = [review_draft_tool]
    
    # Force function calling for structured review execution
    reviewer_llm_forced = reviewer_llm.bind_tools(
        reviewer_tools,
        tool_choice={"type": "function", "function": {"name": "review_draft_tool"}}
    )
    
    reviewer_runnable = create_agent(
        model=reviewer_llm_forced,
        tools=reviewer_tools,
        system_prompt=REVIEWER_AGENT_PROMPT,
    )
    
    return CompiledSubAgent(
        name="reviewer_agent",
        description=REVIEWER_AGENT_DESCRIPTION,
        runnable=reviewer_runnable,
    )

reviewer_agent = get_reviewer_agent()
