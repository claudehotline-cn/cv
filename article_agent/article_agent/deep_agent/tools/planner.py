"""Article Deep Agent Tools - Planner Agent"""
from __future__ import annotations

import logging
import os
import json
import re
import uuid
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from ...config.llm_runtime import build_chat_llm
from ..utils.logging.tools_logging import log_performance, log_llm_response, log_tool_output, _LOGGER as COMMON_LOGGER
from ..utils.artifacts import get_current_article_id, save_article_artifact, load_article_artifact
from .prompts import PLANNER_OUTLINE_SYSTEM_PROMPT, PLANNER_OUTLINE_USER_PROMPT

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.planner")

# ============================================================================
# Collector Tools (Merged from collector.py)
# ============================================================================

@tool
def fetch_url_tool(url: str, max_images: int = 30, max_text_chars: int = 60000) -> Dict[str, Any]:
    """抓取 URL 内容，提取文本和图片。
    
    Args:
        url: 要抓取的 URL
        max_images: 最大图片数
        max_text_chars: 最大文本字符数
        
    Returns:
        包含 title, text, images 的字典
    """
    from ..utils.files import fetch_url_with_images
    
    _LOGGER.info(f"fetch_url_tool called with url: {url[:50]}...")
    try:
        data = fetch_url_with_images(url, max_images=max_images, max_text_chars=max_text_chars)
        text = data.get("text") or ""
        images = data.get("images") or []
        
        # 格式化图片列表
        formatted_images = [
            {
                "path_or_url": (img.get("url") or img.get("src") or ""),
                "alt": (img.get("alt") or ""),
            }
            for img in images
            if isinstance(img, dict) and (img.get("url") or img.get("src"))
        ]
        
        _LOGGER.info(f"fetch_url_tool success: {len(text)} chars, {len(formatted_images)} images")
        return {
            "title": data.get("title", ""),
            "text": text,
            "images": formatted_images,
            "success": True,
        }
    except Exception as exc:
        _LOGGER.warning(f"fetch_url_tool failed: {exc}")
        return {
            "title": "",
            "text": "",
            "images": [],
            "success": False,
            "error": str(exc),
        }


@tool
def load_file_tool(file_path: str, max_text_chars: int = 60000) -> Dict[str, Any]:
    """加载本地文件内容。
    
    Args:
        file_path: 本地文件路径
        max_text_chars: 最大文本字符数
        
    Returns:
        包含 title, text 的字典
    """
    from ..utils.files import load_text_from_file
    
    _LOGGER.info(f"load_file_tool called with file_path: {file_path}")
    try:
        data = load_text_from_file(file_path, max_text_chars=max_text_chars)
        text = data.get("text") or ""
        
        _LOGGER.info(f"load_file_tool success: {len(text)} chars")
        return {
            "title": data.get("path", file_path),
            "text": text,
            "success": True,
        }
    except Exception as exc:
        _LOGGER.warning(f"load_file_tool failed: {exc}")
        return {
            "title": file_path,
            "text": "",
            "success": False,
            "error": str(exc),
        }


@tool
def collect_all_sources_tool(
    urls: List[str],
    file_paths: List[str],
) -> Dict[str, Any]:
    """收集所有素材来源，返回 CollectorOutput。
    
    Args:
        urls: URL 列表
        file_paths: 文件路径列表
        
    Returns:
        CollectorOutput 字典
    """
    from ..utils.files import fetch_url_with_images, load_text_from_file
    
    # 固定参数，不允许 LLM 覆盖
    max_text_chars = 5000  # 限制每个源的最大读取字符数，避免 Context 过长
    max_overview_chars = 2000
    max_images_per_source = 30
    
    _LOGGER.info(f"collect_all_sources_tool called with {len(urls or [])} urls, {len(file_paths or [])} files, max_text_chars={max_text_chars}")
    
    sources = []
    overview_parts = []
    total_text_chars = 0
    total_images = 0
    
    # 处理 URLs
    for idx, url in enumerate(urls or []):
        try:
            data = fetch_url_with_images(url, max_images=max_images_per_source, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            images = data.get("images") or []
            
            formatted_images = [
                {
                    "path_or_url": (img.get("url") or img.get("src") or ""),
                    "alt": (img.get("alt") or ""),
                }
                for img in images
                if isinstance(img, dict) and (img.get("url") or img.get("src"))
            ]
            
            sources.append({
                "url": url,
                "title": data.get("title", ""),
                "text_preview": snippet,
                "full_text": text,  # 保存全文供落盘
                "images": formatted_images,
            })
            
            total_text_chars += len(text)
            total_images += len(formatted_images)
            overview_parts.append(f"- [{data.get('title', 'URL')}]({url}): {len(text)} 字符")
            
            _LOGGER.info(f"Collected source {idx}: {len(text)} chars from {url}")
        except Exception as exc:
            _LOGGER.warning(f"Failed to collect {url}: {exc}")
            overview_parts.append(f"- [错误] {url}: {exc}")
    
    # 处理文件
    for idx, path in enumerate(file_paths or []):
        try:
            data = load_text_from_file(path, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            
            sources.append({
                "url": path,
                "title": path,
                "text_preview": snippet,
                "full_text": text,  # 保存全文供落盘
                "images": [],
            })
            
            total_text_chars += len(text)
            overview_parts.append(f"- [文件] {path}: {len(text)} 字符")
            
            _LOGGER.info(f"Collected file {idx}: {len(text)} chars")
        except Exception as exc:
            _LOGGER.warning(f"Failed to collect file {path}: {exc}")
            overview_parts.append(f"- [错误] {path}: {exc}")
    
    overview = "## 素材概览\n\n" + "\n".join(overview_parts) + f"\n\n**总计**: {total_text_chars} 字符, {total_images} 图片"
    
    # 落盘：保存素材到文件供其他 SubAgent 读取
    
    # 落盘：保存素材到文件供其他 SubAgent 读取
    article_id = get_current_article_id()
    
    # 保存完整素材到 JSON 文件 (包含 full_text)
    sources_data = {
        "sources": sources,
        "overview": overview
    }
    sources_file = save_article_artifact(article_id, "sources.json", sources_data)
        
    _LOGGER.info(f"Sources saved to: {sources_file}")
    
    # 返回给 Agent 的结果中移除 full_text，减少 token 消耗
    lightweight_sources = []
    for s in sources:
        s_copy = s.copy()
        if "full_text" in s_copy:
            del s_copy["full_text"]
        lightweight_sources.append(s_copy)

    # 记录详细输出
    log_tool_output("collect_all_sources_tool", {"overview": overview, "source_count": len(sources)})
    
    # 只返回文件路径和摘要信息，不返回完整 sources 列表
    result = {
        "article_id": article_id,
        "sources_file": sources_file,  # 告诉后续 Agent 文件位置
        "overview": overview,
        "total_text_chars": total_text_chars,
        "total_images": total_images,
        "sources_count": len(sources),
    }
    return result


@tool
def read_sources_tool(sources_file: str = "") -> Dict[str, Any]:
    """读取之前收集的素材（供 Researcher 和 Writer 使用）。
    
    Args:
        sources_file: 素材文件路径（可选，如果为空则自动查找）
        
    Returns:
        包含 sources, overview, total_text_chars, total_images 的字典
    """
    
    # 如果没有指定文件，尝试从环境变量获取当前文章目录
    if not sources_file:
        article_id = get_current_article_id()
        if article_id:
            from ...config import get_article_dir
            article_dir = get_article_dir(article_id)
            sources_file = os.path.join(article_dir, "sources.json")
    
    if not sources_file or not os.path.exists(sources_file):
        _LOGGER.warning(f"Sources file not found: {sources_file}")
        return {
            "sources": [],
            "overview": "素材文件未找到",
            "total_text_chars": 0,
            "total_images": 0,
            "error": "素材文件未找到，请先调用 collect_all_sources_tool 收集素材",
        }
    
    try:
        with open(sources_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        _LOGGER.info(f"Loaded sources from {sources_file}: {len(data.get('sources', []))} sources")
        return data
    except Exception as exc:
        _LOGGER.error(f"Failed to read sources file: {exc}")
        return {
            "sources": [],
            "overview": f"读取素材文件失败: {exc}",
            "total_text_chars": 0,
            "total_images": 0,
            "error": str(exc),
        }


# ============================================================================
# Planner Tools
# ============================================================================

@tool
def generate_outline_tool(instruction: str, overview: str, target_word_count: int = 3000, article_id: str = "") -> Dict[str, Any]:
    """根据用户指令和素材概览生成文章大纲。
    
    Args:
        instruction: 用户写作指令
        overview: 素材概览
        target_word_count: 目标总字数
        article_id: 文章 ID (必须与 collect_all_sources_tool 返回的一致)
        
    Returns:
        OutlineOutput 字典
    """
    
    _LOGGER.info(f"generate_outline_tool called with target_word_count: {target_word_count}")
    
    system_prompt = PLANNER_OUTLINE_SYSTEM_PROMPT.format(target_word_count=target_word_count)

    user_prompt = PLANNER_OUTLINE_USER_PROMPT.format(instruction=instruction, overview=overview)

    try:
        with log_performance("generate_outline", target_word_count=target_word_count):
            llm = build_chat_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            input_chars = len(system_prompt) + len(user_prompt)
            response = llm.invoke(messages)
            
            # 记录 LLM 响应详情
            log_llm_response("generate_outline", response, input_chars=input_chars)
            
            content = response.content.strip()
            
            if not content:
                _LOGGER.error(f"generate_outline_tool: LLM returned empty content. Metadata: {response.response_metadata}")
                return {
                    "title": "生成失败",
                    "sections": [],
                    "estimated_total_chars": 0,
                    "error": "LLM 返回内容为空",
                }
        
        # 尝试提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            
            # 落盘：保存大纲到文件
            try:
                # 如果参数没传，从环境变量获取
                save_article_id = get_current_article_id(article_id)
                _LOGGER.info(f"[DEBUG] generate_outline_tool: save_article_id = '{save_article_id}'")
                
                if save_article_id:
                    outline_file = save_article_artifact(save_article_id, "outline.json", result)
                    _LOGGER.info(f"Outline saved to: {outline_file}")
                else:
                    _LOGGER.warning("[DEBUG] generate_outline_tool: article_id is EMPTY, cannot save outline!")
            except Exception as e:
                _LOGGER.warning(f"Failed to save outline to file: {e}")
            
            # 记录完整大纲结构
            sections = result.get("sections", [])
            sections_str = ", ".join([f"{s.get('id', '')}:{s.get('title', '')}" for s in sections])
            _LOGGER.info(f"[OUTLINE] 标题: {result.get('title', '')}")
            _LOGGER.info(f"[OUTLINE] 章节({len(sections)}): {sections_str}")
            _LOGGER.info(f"[OUTLINE] 预估字数: {result.get('estimated_total_chars', 0)}")
            
         
            # 落盘保存 (备用路径，已在上面保存过了)
            outline_file = "" 
            try:
               if save_article_id:
                    from ...config import get_article_dir
                    save_dir = get_article_dir(save_article_id)
                    outline_file = os.path.join(save_dir, "outline.json")
            except Exception as e:
                _LOGGER.warning(f"Failed to get outline path: {e}")
            
            _LOGGER.info(f"generate_outline_tool success: {len(result.get('sections', []))} sections")
            # 只返回文件路径，不返回内存对象
            return {
                "article_id": article_id,
                "outline_path": outline_file,
                "sections_count": len(result.get("sections", [])),
                "title": result.get("title", ""),
            }
        else:
            _LOGGER.warning(f"generate_outline_tool: no JSON found in response")
            return {
                "title": "未知标题",
                "sections": [],
                "estimated_total_chars": 0,
                "error": "无法解析 LLM 响应",
            }
    except Exception as exc:
        _LOGGER.error(f"generate_outline_tool failed: {exc}")
        return {
            "title": "错误",
            "sections": [],
            "estimated_total_chars": 0,
            "error": str(exc),
        }
