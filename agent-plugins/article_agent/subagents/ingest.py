"""Ingest Sub-Agent Module"""
from __future__ import annotations

import logging
from deepagents import CompiledSubAgent
from langchain.agents import create_agent
from agent_core.runtime import build_chat_llm

from ..prompts import INGEST_AGENT_PROMPT, INGEST_AGENT_DESCRIPTION
from ..schemas import IngestOutput
from ..tools import ingest_documents_tool

_LOGGER = logging.getLogger(__name__)

def get_ingest_agent() -> CompiledSubAgent:
    """Create Ingest Sub-Agent."""
    ingest_llm = build_chat_llm(task_name="ingest")
    ingest_tools = [ingest_documents_tool]
    ingest_llm_forced = ingest_llm.bind_tools(ingest_tools, tool_choice="required")
    
    ingest_runnable = create_agent(
        model=ingest_llm_forced,
        tools=ingest_tools,
        system_prompt=INGEST_AGENT_PROMPT,
        response_format=IngestOutput,
    )
    
    return CompiledSubAgent(
        name="ingest_agent",
        description=INGEST_AGENT_DESCRIPTION,
        runnable=ingest_runnable,
    )

ingest_agent = get_ingest_agent()
