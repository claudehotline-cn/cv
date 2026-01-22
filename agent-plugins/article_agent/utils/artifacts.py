"""Article Deep Agent Utils - Artifact Persistence Helpers"""
from __future__ import annotations

import logging
import os
import json
import contextvars
import uuid
import glob
import asyncio
from typing import Any, Dict, List, Optional, Tuple

from ..config import get_article_dir, get_drafts_dir, get_final_article_dir

_LOGGER = logging.getLogger("article_agent.deep_agent.utils.artifacts")

__all__ = [
    "get_current_article_id",
    "set_current_article_id",
    "load_article_artifact",
    "save_article_artifact",
    "save_draft_file",
    "find_draft_files",
    "get_article_dir",
    "get_drafts_dir",
    "get_final_article_dir",
    "get_corpus_dir",
    "ensure_corpus_dir",
]

# ContextVar to store article_id for the current request context
_ARTICLE_ID_CTX = contextvars.ContextVar("article_id", default="")

def get_current_article_id(arg_id: str = "") -> str:
    """获取当前文章 ID。优先使用参数，其次使用 ContextVar，最后尝试环境变量。
    """
    article_id = arg_id
    
    # 1. 尝试从 ContextVar 获取
    ctx_id = _ARTICLE_ID_CTX.get()
    
    # 2. 尝试从环境变量获取 (Legacy fallback)
    env_id = os.environ.get("ARTICLE_CURRENT_ID", "")
    
    # Robustness strategy
    if env_id and article_id in ["001", "1", "default", "placeholder"]:
        article_id = env_id
    
    article_id = article_id or ctx_id or env_id
    
    if article_id and article_id.startswith("article_"):
        article_id = article_id[len("article_"):]
    
    # 注意：这里不再自动生成 ID，逻辑上应由 Middleware 显式调用 set 生成
    
    return article_id

def set_current_article_id(article_id: str):
    """设置当前 Context 的 Article ID。"""
    if article_id.startswith("article_"):
        article_id = article_id[len("article_"):]
    _ARTICLE_ID_CTX.set(article_id)
    # 保持环境变量同步以兼容旧代码
    os.environ["ARTICLE_CURRENT_ID"] = article_id


def get_corpus_dir(article_id: str, doc_id: str) -> str:
    """获取指定文档的 corpus 目录 (artifacts/article_{id}/corpus/{doc_id})。"""
    article_dir = get_article_dir(article_id)
    return os.path.join(article_dir, "corpus", doc_id)

async def ensure_corpus_dir(article_id: str, doc_id: str) -> Tuple[str, str]:
    """确保 corpus 目录结构存在，返回 (corpus_dir, parsed_dir)。
    
    创建目录结构（异步，不阻塞事件循环）：
    - artifacts/article_{id}/corpus/{doc_id}/
    - artifacts/article_{id}/corpus/{doc_id}/parsed/
    """
    corpus_dir = get_corpus_dir(article_id, doc_id)
    parsed_dir = os.path.join(corpus_dir, "parsed")
    # 使用 asyncio.to_thread 避免阻塞事件循环
    await asyncio.to_thread(os.makedirs, parsed_dir, exist_ok=True)
    _LOGGER.info(f"Ensured corpus directory: {parsed_dir}")
    return corpus_dir, parsed_dir

# 架构文档要求的子目录映射
ARTIFACT_SUBDIRS = {
    # plans/
    "outline.json": "plans",
    "section_plan.json": "plans",
    "open_questions.json": "plans",
    # research/
    "research_notes.json": "research",
    # draft/ (citations_map 属于 draft)
    "citations_map.json": "draft",
    # review/
    "review_report.json": "review",
}

def _get_artifact_path(article_dir: str, artifact_name: str) -> str:
    """根据 artifact 名称确定子目录路径。"""
    subdir = ARTIFACT_SUBDIRS.get(artifact_name, "")
    if subdir:
        return os.path.join(article_dir, subdir, artifact_name)
    return os.path.join(article_dir, artifact_name)

def load_article_artifact(article_id: str, artifact_name: str) -> Dict[str, Any]:
    """从文章目录加载 JSON artifact (e.g., outline.json, sources.json)。"""
    if not article_id:
        return {}
        
    article_dir = get_article_dir(article_id)
    
    # 优先使用子目录路径
    file_path = _get_artifact_path(article_dir, artifact_name)
    
    # 兼容旧路径（根目录）
    if not os.path.exists(file_path):
        file_path_legacy = os.path.join(article_dir, artifact_name)
        if os.path.exists(file_path_legacy):
            file_path = file_path_legacy
            _LOGGER.debug(f"Using legacy path for {artifact_name}")
    
    if os.path.exists(file_path):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            _LOGGER.info(f"Loaded artifact {artifact_name} from {file_path}")
            return data
        except Exception as e:
            _LOGGER.warning(f"Failed to load artifact {artifact_name}: {e}")
            return {}
    return {}

def save_article_artifact(article_id: str, artifact_name: str, data: Dict[str, Any]) -> str:
    """保存 JSON artifact 到文章目录（按架构子目录）。返回保存的文件路径。"""
    if not article_id:
        _LOGGER.warning(f"Cannot save artifact {artifact_name}: Empty article_id")
        return ""
        
    article_dir = get_article_dir(article_id)
    file_path = _get_artifact_path(article_dir, artifact_name)
    
    # 确保子目录存在
    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        _LOGGER.info(f"Saved artifact {artifact_name} to {file_path}")
        return file_path
    except Exception as e:
        _LOGGER.warning(f"Failed to save artifact {artifact_name}: {e}")
        return ""

def save_draft_file(article_id: str, section_id: str, content: str) -> str:
    """保存草稿文件 (.md)。"""
    if not article_id:
        return ""
        
    drafts_dir = get_drafts_dir(article_id)
    os.makedirs(drafts_dir, exist_ok=True)
    
    file_name = f"section_{section_id}.md"
    file_path = os.path.join(drafts_dir, file_name)
    
    try:
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        _LOGGER.info(f"Saved draft {section_id} to {file_path}")
        return file_path
    except Exception as e:
        _LOGGER.warning(f"Failed to save draft {section_id}: {e}")
        return ""

def find_draft_files(article_id: str) -> List[str]:
    """查找文章的所有草稿文件。"""
    if not article_id:
        return []
        
    drafts_dir = get_drafts_dir(article_id)
    if not os.path.exists(drafts_dir):
        return []
        
    return glob.glob(os.path.join(drafts_dir, "section_*.md"))
