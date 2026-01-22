"""Writer Sub-Agent Module"""
from __future__ import annotations

import logging
from deepagents import CompiledSubAgent
from langchain.agents import create_agent
from agent_core.runtime import build_chat_llm

from ..prompts import WRITER_AGENT_PROMPT, WRITER_AGENT_DESCRIPTION
from ..tools import write_all_sections_tool

_LOGGER = logging.getLogger(__name__)

def get_writer_agent() -> CompiledSubAgent:
    """Create Writer Sub-Agent."""
    writer_llm = build_chat_llm(task_name="writer")
    writer_tools = [write_all_sections_tool]
    
    # Force function calling for structured writing execution
    writer_llm_forced = writer_llm.bind_tools(
        writer_tools,
        tool_choice={"type": "function", "function": {"name": "write_all_sections_tool"}}
    )
    
    writer_runnable = create_agent(
        model=writer_llm_forced,
        tools=writer_tools,
        system_prompt=WRITER_AGENT_PROMPT,
    )
    
    return CompiledSubAgent(
        name="writer_agent",
        description=WRITER_AGENT_DESCRIPTION,
        runnable=writer_runnable,
    )

writer_agent = get_writer_agent()
