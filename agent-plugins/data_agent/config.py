"""Data Agent Configuration.

This module provides data-agent-specific configuration and path helpers
built on top of agent_core.WorkspaceBackend.
"""
from __future__ import annotations

from typing import Optional

from agent_core import WorkspaceBackend


# Agent name constant for this plugin
AGENT_NAME = "data_agent"


def get_backend(user_id: str, session_id: str, task_id: Optional[str] = None) -> WorkspaceBackend:
    """Get WorkspaceBackend instance for data_agent.
    
    Args:
        user_id: User identifier (top-level directory)
        session_id: Session identifier (maps to session_id in backend)
        task_id: Analysis ID or Task ID (maps to task_id in backend)
        
    Returns:
        WorkspaceBackend configured for data_agent
    """
    return WorkspaceBackend(AGENT_NAME, user_id, session_id, task_id)


__all__ = [
    "AGENT_NAME",
    "get_backend",
]
