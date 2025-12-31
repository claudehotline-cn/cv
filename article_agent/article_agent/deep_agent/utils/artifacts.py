"""Article Deep Agent Utils - Artifact Persistence Helpers"""
from __future__ import annotations

import logging
import os
import json
import uuid
import glob
from typing import Any, Dict, List, Optional

from ...config import get_article_dir, get_drafts_dir, get_final_article_dir

_LOGGER = logging.getLogger("article_agent.deep_agent.utils.artifacts")

__all__ = [
    "get_current_article_id",
    "load_article_artifact",
    "save_article_artifact",
    "save_draft_file",
    "find_draft_files",
    "get_article_dir",
    "get_drafts_dir",
    "get_final_article_dir",
]

def get_current_article_id(arg_id: str = "") -> str:
    """获取当前文章 ID。优先使用参数，其次使用环境变量，最后生成新的。
    
    Side Effect: 如果环境变量未设置，会同时设置 ARTICLE_CURRENT_ID。
    """
    article_id = arg_id or os.environ.get("ARTICLE_CURRENT_ID", "")
    if not article_id:
         # 如果完全没有 ID，生成一个新的 (通常 Planner 会做这步)
         article_id = str(uuid.uuid4())[:8]
    
    # 确保环境变量同步，供后续步骤使用
    os.environ["ARTICLE_CURRENT_ID"] = article_id
    return article_id

def load_article_artifact(article_id: str, artifact_name: str) -> Dict[str, Any]:
    """从文章目录加载 JSON artifact (e.g., outline.json, sources.json)。"""
    if not article_id:
        return {}
        
    article_dir = get_article_dir(article_id)
    file_path = os.path.join(article_dir, artifact_name)
    
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
    """保存 JSON artifact 到文章目录。返回保存的文件路径。"""
    if not article_id:
        _LOGGER.warning(f"Cannot save artifact {artifact_name}: Empty article_id")
        return ""
        
    article_dir = get_article_dir(article_id)
    os.makedirs(article_dir, exist_ok=True)
    
    file_path = os.path.join(article_dir, artifact_name)
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
