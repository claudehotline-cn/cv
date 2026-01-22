"""Data Agent Artifact Persistence Helpers.

Encapsulates all file system operations for Data Agent, replacing direct
Backend access in tools and merging dataframe_store functionality.
"""
from __future__ import annotations

import logging
import json
import os
import shutil
import uuid
import pandas as pd
from typing import Any, Dict, List, Optional, Union

from agent_core import WorkspaceBackend
from ..config import AGENT_NAME

_LOGGER = logging.getLogger("data_agent.utils.artifacts")


# ========== Backend Factory ==========

def get_backend_from_config(config: Dict[str, Any]) -> WorkspaceBackend:
    """Create WorkspaceBackend using identity from runnable config.
    
    Extracts user_id, session_id, and analysis_id (mapped to task_id).
    
    Args:
        config: LangChain RunnableConfig (or similar dict with 'configurable')
    """
    configurable = config.get("configurable", {})
    user_id = configurable.get("user_id", "anonymous")
    session_id = configurable.get("session_id", "default")
    analysis_id = configurable.get("analysis_id", "")
    
    # Task ID mapping:
    # If analysis_id is present, it's an async Data Analysis task.
    # Otherwise check for generic task_id, else None (Sync)
    task_id = None
    if analysis_id:
        task_id = f"data_analysis_{analysis_id}"
    else:
        task_id = configurable.get("task_id")
        
    return WorkspaceBackend(AGENT_NAME, user_id, session_id, task_id)


def get_backend_by_ids(
    user_id: str, 
    session_id: str, 
    analysis_id: Optional[str] = None
) -> WorkspaceBackend:
    """Create WorkspaceBackend using explicit IDs."""
    task_id = f"data_analysis_{analysis_id}" if analysis_id else None
    return WorkspaceBackend(AGENT_NAME, user_id, session_id, task_id)


# ========== DataFrames (Merged from dataframe_store.py) ==========

def store_dataframe(
    name: str, 
    df: pd.DataFrame, 
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> str:
    """Store DataFrame to Parquet."""
    if not analysis_id:
        _LOGGER.error("store_dataframe called without analysis_id")
        return ""
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    
    # Structure: .../tasks/{task_id}/dataframes/{name}.parquet
    relative_path = f"dataframes/{name}.parquet"
    filepath = os.path.join(backend.artifacts_dir, relative_path)
    
    backend.ensure_dir("dataframes")
    
    try:
        df.to_parquet(filepath, index=False)
        _LOGGER.info("Stored DataFrame '%s': shape=%s -> %s", name, df.shape, filepath)
        return filepath
    except Exception as e:
        _LOGGER.error("Failed to store DataFrame '%s': %s", name, e)
        return ""


def get_dataframe(
    name: str, 
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> Optional[pd.DataFrame]:
    """Load DataFrame from Parquet."""
    if not analysis_id:
        return None
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    filepath = os.path.join(backend.artifacts_dir, f"dataframes/{name}.parquet")
    
    if not os.path.exists(filepath):
        return None
        
    try:
        df = pd.read_parquet(filepath)
        _LOGGER.debug("Loaded DataFrame '%s': shape=%s", name, df.shape)
        return df
    except Exception as e:
        _LOGGER.error("Failed to load DataFrame '%s': %s", name, e)
        return None


def list_dataframes(
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> List[str]:
    """List available DataFrames for analysis."""
    if not analysis_id:
        return []
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    dataframes_dir = os.path.join(backend.artifacts_dir, "dataframes")
    
    if not os.path.exists(dataframes_dir):
        return []
        
    return [
        f.replace(".parquet", "") 
        for f in os.listdir(dataframes_dir) 
        if f.endswith(".parquet")
    ]


def clear_dataframes(
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> None:
    """Clear all DataFrames for analysis."""
    if not analysis_id:
        return
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    dataframes_dir = os.path.join(backend.artifacts_dir, "dataframes")
    
    if os.path.exists(dataframes_dir):
        shutil.rmtree(dataframes_dir)


# ========== Charts & Reports ==========

def save_chart(
    chart_data: Union[str, Dict], 
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> str:
    """Save chart configuration JSON."""
    if not analysis_id:
        return ""
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    
    try:
        data = chart_data if isinstance(chart_data, dict) else json.loads(chart_data)
        
        # 1. Save main chart.json (latest state)
        backend.write_json("chart.json", data)
        
        # 2. Save history entry
        hist_path = f"charts/chart_{uuid.uuid4().hex[:8]}.json"
        return backend.write_json(hist_path, data)
    except Exception as e:
        _LOGGER.error("Failed to save chart: %s", e)
        return ""


def load_chart(
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> Optional[Dict]:
    """Load latest chart configuration."""
    if not analysis_id:
        return None
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    return backend.read_json("chart.json")


def save_report(
    content: str, 
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> str:
    """Save Markdown report."""
    if not analysis_id:
        return ""
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    return backend.write_text("report.md", content)


def load_report(
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> str:
    """Load Markdown report."""
    if not analysis_id:
        return ""
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    return backend.read_text("report.md")


def save_sql_csv(
    rows: List[Dict], 
    columns: List[str], 
    analysis_id: str, 
    user_id: str = "anonymous",
    session_id: str = "default"
) -> str:
    """Save SQL results as CSV."""
    if not analysis_id:
        return ""
        
    backend = get_backend_by_ids(user_id, session_id, analysis_id)
    
    csv_dir = backend.ensure_dir("sql_results")
    filepath = os.path.join(csv_dir, f"sql_{uuid.uuid4().hex[:8]}.csv")
    
    try:
        pd.DataFrame(rows, columns=columns).to_csv(filepath, index=False)
        return filepath
    except Exception as e:
        _LOGGER.error("Failed to save SQL CSV: %s", e)
        return ""


__all__ = [
    "get_backend_from_config",
    "get_backend_by_ids",
    "store_dataframe",
    "get_dataframe",
    "list_dataframes",
    "clear_dataframes",
    "save_chart",
    "load_chart",
    "save_report",
    "load_report",
    "save_sql_csv",
]
