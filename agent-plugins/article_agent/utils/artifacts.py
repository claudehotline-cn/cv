"""Article Agent Artifact Persistence Helpers.

Provides high-level functions for saving/loading article-specific artifacts
using the shared WorkspaceBackend from agent_core.
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

from agent_core import WorkspaceBackend

from ..config import AGENT_NAME

_LOGGER = logging.getLogger("article_agent.utils.artifacts")


def get_backend(article_id: str, task_id: Optional[str] = None, user_id: str = "default") -> WorkspaceBackend:
    """Get WorkspaceBackend for article operations."""
    clean_id = article_id
    if clean_id.startswith("article_"):
        clean_id = clean_id[len("article_"):]
    return WorkspaceBackend(AGENT_NAME, user_id, clean_id, task_id)


# Artifact subdirectory mapping per architecture spec
ARTIFACT_SUBDIRS = {
    "outline.json": "plans",
    "section_plan.json": "plans",
    "open_questions.json": "plans",
    "research_notes.json": "research",
    "citations_map.json": "draft",
    "review_report.json": "review",
}


def _get_artifact_relative_path(article_id: str, artifact_name: str) -> str:
    """Get relative path for artifact within artifacts_dir."""
    clean_id = article_id
    if clean_id.startswith("article_"):
        clean_id = clean_id[len("article_"):]
    
    subdir = ARTIFACT_SUBDIRS.get(artifact_name, "")
    base = f"article_{clean_id}"
    
    if subdir:
        return os.path.join(base, subdir, artifact_name)
    return os.path.join(base, artifact_name)


# ========== Sync Functions ==========

def load_article_artifact(
    article_id: str, 
    artifact_name: str, 
    task_id: Optional[str] = None,
    user_id: str = "default"
) -> Dict[str, Any]:
    """Load JSON artifact from article directory."""
    if not article_id:
        return {}
    
    backend = get_backend(article_id, task_id, user_id)
    rel_path = _get_artifact_relative_path(article_id, artifact_name)
    
    # Try subdirectory path first
    data = backend.read_json(rel_path)
    if data:
        return data
    
    # Fallback to legacy root path
    clean_id = article_id.removeprefix("article_")
    legacy_path = os.path.join(f"article_{clean_id}", artifact_name)
    return backend.read_json(legacy_path)


def save_article_artifact(
    article_id: str, 
    artifact_name: str, 
    data: Dict[str, Any], 
    task_id: Optional[str] = None,
    user_id: str = "default"
) -> str:
    """Save JSON artifact to article directory. Returns saved path."""
    if not article_id:
        _LOGGER.warning(f"Cannot save artifact {artifact_name}: Empty article_id")
        return ""
    
    backend = get_backend(article_id, task_id, user_id)
    rel_path = _get_artifact_relative_path(article_id, artifact_name)
    return backend.write_json(rel_path, data)


def save_draft_file(
    article_id: str, 
    section_id: str, 
    content: str, 
    task_id: Optional[str] = None,
    user_id: str = "default"
) -> str:
    """Save draft markdown file."""
    if not article_id:
        return ""
    
    backend = get_backend(article_id, task_id, user_id)
    clean_id = article_id.removeprefix("article_")
    rel_path = os.path.join(f"article_{clean_id}", "drafts", f"section_{section_id}.md")
    return backend.write_text(rel_path, content)


def find_draft_files(article_id: str, task_id: Optional[str] = None, user_id: str = "default") -> List[str]:
    """Find all draft files for an article."""
    if not article_id:
        return []
    
    backend = get_backend(article_id, task_id, user_id)
    clean_id = article_id.removeprefix("article_")
    return backend.list_files(os.path.join(f"article_{clean_id}", "drafts"), "section_*.md")


def get_corpus_dir(article_id: str, doc_id: str, task_id: Optional[str] = None, user_id: str = "default") -> str:
    """Get corpus directory path for a document."""
    backend = get_backend(article_id, task_id, user_id)
    clean_id = article_id.removeprefix("article_")
    return os.path.join(backend.artifacts_dir, f"article_{clean_id}", "corpus", doc_id)


# ========== Async Functions ==========

async def ensure_corpus_dir(
    article_id: str, 
    doc_id: str, 
    task_id: Optional[str] = None,
    user_id: str = "default"
) -> Tuple[str, str]:
    """Ensure corpus directory structure exists. Returns (corpus_dir, parsed_dir)."""
    backend = get_backend(article_id, task_id, user_id)
    clean_id = article_id.removeprefix("article_")
    
    corpus_rel = os.path.join(f"article_{clean_id}", "corpus", doc_id)
    parsed_rel = os.path.join(corpus_rel, "parsed")
    
    parsed_dir = await backend.aensure_dir(parsed_rel)
    corpus_dir = os.path.dirname(parsed_dir)
    
    _LOGGER.info(f"Ensured corpus directory: {parsed_dir}")
    return corpus_dir, parsed_dir


# ========== Path Helper (for backward compatibility) ==========

def get_article_dir(article_id: str, task_id: Optional[str] = None, user_id: str = "default") -> str:
    """Get article artifacts directory path."""
    backend = get_backend(article_id, task_id, user_id)
    clean_id = article_id.removeprefix("article_")
    return os.path.join(backend.artifacts_dir, f"article_{clean_id}")


def get_drafts_dir(article_id: str, task_id: Optional[str] = None, user_id: str = "default") -> str:
    """Get drafts directory path."""
    return os.path.join(get_article_dir(article_id, task_id, user_id), "drafts")


def get_final_article_dir(article_id: str, task_id: Optional[str] = None, user_id: str = "default") -> str:
    """Get final article directory path."""
    return os.path.join(get_article_dir(article_id, task_id, user_id), "article")


__all__ = [
    # Core functions
    "get_backend",
    "load_article_artifact",
    "save_article_artifact",
    "save_draft_file",
    "find_draft_files",
    "get_corpus_dir",
    "ensure_corpus_dir",
    # Path helpers (backward compat)
    "get_article_dir",
    "get_drafts_dir", 
    "get_final_article_dir",
]
