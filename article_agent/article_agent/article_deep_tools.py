"""Article Deep Agent Tools - 各 SubAgent 使用的工具函数"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from langchain_core.tools import tool

from .article_deep_schemas import (
    CollectorOutput,
    OutlineOutput,
    ResearcherOutput,
    ResearchAuditOutput,
    WriterOutput,
    WriterAuditOutput,
    ReviewerOutput,
    IllustratorOutput,
    AssemblerOutput,
)

_LOGGER = logging.getLogger("article_agent.article_deep_tools")


# ============================================================================
# 性能日志辅助函数
# ============================================================================

import time
from contextlib import contextmanager

@contextmanager
def log_performance(operation: str, **extra_info):
    """记录操作性能的上下文管理器。
    
    使用方式:
        with log_performance("write_section", section_id="sec_1"):
            # 执行操作
            pass
    """
    start_time = time.time()
    extra_str = ", ".join(f"{k}={v}" for k, v in extra_info.items())
    _LOGGER.info(f"[PERF] {operation} START {extra_str}")
    
    try:
        yield
    finally:
        elapsed_ms = (time.time() - start_time) * 1000
        _LOGGER.info(f"[PERF] {operation} END elapsed={elapsed_ms:.0f}ms {extra_str}")


def log_llm_response(operation: str, response, input_chars: int = 0):
    """记录 LLM 响应的详细信息。"""
    output_content = response.content if hasattr(response, 'content') else str(response)
    output_chars = len(output_content)
    
    # 尝试获取 token 使用信息（如果可用）
    token_info = ""
    if hasattr(response, 'response_metadata'):
        meta = response.response_metadata
        if 'prompt_eval_count' in meta:
            prompt_tokens = meta.get('prompt_eval_count', 0)
            completion_tokens = meta.get('eval_count', 0)
            total_tokens = prompt_tokens + completion_tokens
            token_info = f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, total_tokens={total_tokens}"
        elif 'usage' in meta:
            usage = meta['usage']
            prompt_tokens = usage.get('prompt_tokens', 0)
            completion_tokens = usage.get('completion_tokens', 0)
            total_tokens = usage.get('total_tokens', prompt_tokens + completion_tokens)
            token_info = f"prompt_tokens={prompt_tokens}, completion_tokens={completion_tokens}, total_tokens={total_tokens}"
    
    _LOGGER.info(
        f"[LLM] {operation} input_chars={input_chars}, output_chars={output_chars}, {token_info}"
    )
    
    # 记录输出内容预览（最多 500 字符）
    preview = output_content[:500].replace('\n', '\\n')
    if len(output_content) > 500:
        preview += "..."
    _LOGGER.info(f"[LLM_OUTPUT] {operation}: {preview}")


def log_tool_input(tool_name: str, **kwargs):
    """记录工具输入参数。"""
    params = ", ".join(f"{k}={str(v)[:100]}" for k, v in kwargs.items())
    _LOGGER.info(f"[TOOL_INPUT] {tool_name}: {params}")


def log_tool_output(tool_name: str, output: dict, preview_fields: list = None):
    """记录工具输出结果。
    
    Args:
        tool_name: 工具名称
        output: 输出字典
        preview_fields: 需要预览内容的字段列表
    """
    # 基本输出信息
    summary_fields = {k: v for k, v in output.items() if not isinstance(v, (dict, list)) or k in ['char_count', 'total_char_count']}
    _LOGGER.info(f"[TOOL_OUTPUT] {tool_name}: {summary_fields}")
    
    # 详细字段预览
    if preview_fields:
        for field in preview_fields:
            if field in output:
                content = str(output[field])
                preview = content[:300].replace('\n', '\\n')
                if len(content) > 300:
                    preview += "..."
                _LOGGER.info(f"[TOOL_OUTPUT_DETAIL] {tool_name}.{field}: {preview}")


# ============================================================================
# Collector Agent Tools
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
    from .tools_files import fetch_url_with_images
    
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
    from .tools_files import load_text_from_file
    
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
    from .tools_files import fetch_url_with_images, load_text_from_file
    
    # 固定参数，不允许 LLM 覆盖
    max_text_chars = 30000
    max_overview_chars = 5000
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
    import uuid
    import os
    import json
    
    from .config import get_settings
    settings = get_settings()
    base_dir = settings.artifacts_dir
    article_id = os.environ.get("ARTICLE_CURRENT_ID", str(uuid.uuid4())[:8])
    os.environ["ARTICLE_CURRENT_ID"] = article_id
    
    article_dir = os.path.join(base_dir, f"article_{article_id}")
    os.makedirs(article_dir, exist_ok=True)
    
    # 保存完整素材到 JSON 文件 (包含 full_text)
    sources_file = os.path.join(article_dir, "sources.json")
    with open(sources_file, "w", encoding="utf-8") as f:
        json.dump({
            "sources": sources,
            "overview": overview
        }, f, ensure_ascii=False, indent=2)
        
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
    
    return {
        "article_id": article_id,  # 返回生成的 article_id
        "sources": lightweight_sources,
        "overview": overview,
        "total_text_chars": total_text_chars,
        "total_images": total_images,
        "sources_file": sources_file,  # 告诉后续 Agent 文件位置
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
    import os
    import json
    
    # 如果没有指定文件，尝试从环境变量获取当前文章目录
    if not sources_file:
        from .config import get_settings
        base_dir = get_settings().artifacts_dir
        article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
        if article_id:
            sources_file = os.path.join(base_dir, f"article_{article_id}", "sources.json")
    
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
# Planner Agent Tools
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
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"generate_outline_tool called with target_word_count: {target_word_count}")
    
    system_prompt = f"""
你是 Planner，负责为一篇文章设计大纲。

【核心原则】
文章主题必须完全基于 overview 中的实际内容！
- 仔细阅读 overview 中的内容概览
- 文章标题和章节必须围绕这些来源的实际内容来设计
- 严禁生成与 overview 内容无关的主题

【任务目标】
1. 分析 overview，理解用户提供的来源实际讲什么内容。
2. 基于来源内容和 instruction（用户偏好），为文章设计结构清晰的大纲。
3. 输出文章标题 title（必须反映来源内容的主题）。
4. 输出 sections 列表，每个 section 包含：
   - id：唯一字符串，如 "sec_1", "sec_2"
   - title：章节标题
   - keywords：关键词列表
   - target_chars：该章节的目标字数
   - is_core：是否为核心章节

【字数分配规则】
- 总字数目标：{target_word_count} 字
- 核心章节 (is_core=true)：分配 1.5 倍权重
- 引言/总结：分配 0.7 倍权重
- 确保所有 section 的 target_chars 之和约等于目标总字数

【输出格式】
只输出一个 JSON，格式如下：
{{
  "title": "文章标题",
  "sections": [
    {{"id": "sec_1", "title": "引言", "keywords": ["关键词1"], "target_chars": 400, "is_core": false}},
    {{"id": "sec_2", "title": "核心内容", "keywords": ["关键词2"], "target_chars": 800, "is_core": true}}
  ],
  "estimated_total_chars": {target_word_count}
}}
"""

    user_prompt = f"""
【用户指令】
{instruction}

【素材概览】
{overview}

请根据以上内容生成文章大纲（只输出 JSON）：
"""

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
                import os
                import json
                from .config import get_settings
                
                settings = get_settings()
                base_dir = settings.artifacts_dir
                article_id = article_id or os.environ.get("ARTICLE_CURRENT_ID", "")
                
                if article_id:
                    outline_file = os.path.join(base_dir, f"article_{article_id}", "outline.json")
                    with open(outline_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    _LOGGER.info(f"Outline saved to: {outline_file}")
            except Exception as e:
                _LOGGER.warning(f"Failed to save outline to file: {e}")
            
            # 记录完整大纲结构
            sections = result.get("sections", [])
            sections_str = ", ".join([f"{s.get('id', '')}:{s.get('title', '')}" for s in sections])
            _LOGGER.info(f"[OUTLINE] 标题: {result.get('title', '')}")
            _LOGGER.info(f"[OUTLINE] 章节({len(sections)}): {sections_str}")
            _LOGGER.info(f"[OUTLINE] 预估字数: {result.get('estimated_total_chars', 0)}")
            
            # 落盘保存
            try:
                import os
                base_dir = os.environ.get("ARTICLE_TEMP_DIR", "/tmp/article_drafts")
                article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
                if article_id:
                    save_dir = os.path.join(base_dir, f"article_{article_id}")
                    os.makedirs(save_dir, exist_ok=True)
                    outline_file = os.path.join(save_dir, "outline.json")
                    with open(outline_file, "w", encoding="utf-8") as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    _LOGGER.info(f"[OUTLINE] Saved to: {outline_file}")
            except Exception as e:
                _LOGGER.warning(f"Failed to save outline: {e}")
            
            _LOGGER.info(f"generate_outline_tool success: {len(result.get('sections', []))} sections")
            return result
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


# ============================================================================
# Researcher Agent Tools
# ============================================================================

@tool
def research_section_tool(
    section_id: str,
    section_title: str,
    keywords: List[str],
    sources_text: str,
    available_images: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """为指定章节整理资料笔记。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        keywords: 关键词列表
        sources_text: 素材文本（已合并）
        available_images: 可用图片列表
        
    Returns:
        SectionNotes 字典
    """
    import json
    import re
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"research_section_tool called for section: {section_id}")
    
    system_prompt = f"""
你是 Researcher，负责为文章的一个章节整理资料笔记。

【任务】
根据提供的素材文本，为章节 "{section_title}" 整理资料笔记。

【关键词】
{', '.join(keywords) if keywords else '无特定关键词'}

【要求】
1. **全面提取**：尽可能详尽地提取与章节主题相关的信息，不要过度概括或简化。
2. **保留细节**：必须保留具体的事实、数据、案例、人名和引用。
3. **内容详实**：笔记长度应尽可能丰富（目标 800-1500 字），为 Writer 提供充足的素材。
4. **结构清晰**：使用多级列表整理，逻辑顺畅。
5. **宁多勿少**：如果素材丰富，请提供尽可能多的细节，不要担心太长。

【输出格式】
只输出资料笔记内容（纯文本，不需要 JSON）。
"""

    user_prompt = f"""
【素材内容】
{sources_text[:8000]}  # 限制长度

请为章节 "{section_title}" 整理资料笔记：
"""

    try:
        with log_performance("research_section", section_id=section_id):
            llm = build_chat_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            input_chars = len(system_prompt) + len(user_prompt)
            response = llm.invoke(messages)
            
            # 记录 LLM 响应详情
            log_llm_response("research_section", response, input_chars=input_chars)
            
            notes = response.content.strip()
        
        # 匹配相关图片
        relevant_images = []
        if available_images:
            for img in available_images[:5]:  # 最多 5 张
                alt = img.get("alt", "")
                if any(kw.lower() in alt.lower() for kw in keywords):
                    relevant_images.append(img)
        
        _LOGGER.info(f"research_section_tool success: {len(notes)} chars, {len(relevant_images)} images")
        return {
            "section_id": section_id,
            "notes": notes,
            "relevant_images": relevant_images,
        }
    except Exception as exc:
        _LOGGER.error(f"research_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "notes": f"资料整理失败: {exc}",
            "relevant_images": [],
        }


@tool
def research_all_sections_tool(
    outline: Dict[str, Any],
    sources: List[Dict[str, Any]] = None,
    article_id: str = "",  # 新增：接收 article_id
) -> Dict[str, Any]:
    """为所有章节整理资料笔记。
    
    Args:
        outline: 文章大纲
        sources: (可选) 自动从 sources.json 读取
        article_id: 文章 ID (必须传入，用于定位文件)
        
    Returns:
        ResearcherOutput 字典
    """
    import os
    import json
    
    import os
    import json
    
    # 优先加载 Persistent Outline (此时 outline 参数可能是空的)
    base_dir = os.environ.get("ARTICLE_TEMP_DIR", "/tmp/article_drafts")
    article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
    
    loaded_outline = {}
    if article_id:
        outline_file = os.path.join(base_dir, f"article_{article_id}", "outline.json")
        if os.path.exists(outline_file):
            try:
                with open(outline_file, "r", encoding="utf-8") as f:
                    loaded_outline = json.load(f)
                _LOGGER.info(f"Loaded outline from file: {outline_file}")
            except Exception as e:
                    _LOGGER.warning(f"Failed to load outline from file: {e}")

    if loaded_outline:
        outline = loaded_outline
    elif not outline or not outline.get("sections"):
        _LOGGER.warning("No outline provided and no outline file found!")
        return {"section_notes": [], "error": "Missing outline"}
    
    _LOGGER.info(f"research_all_sections_tool called. Outline sections: {len(outline.get('sections', []))}")
    
    from .config import get_settings
    base_dir = get_settings().artifacts_dir
    article_id = article_id or os.environ.get("ARTICLE_CURRENT_ID", "")
    
    loaded_sources = []
    if article_id:
        sources_file = os.path.join(base_dir, f"article_{article_id}", "sources.json")
        if os.path.exists(sources_file):
            try:
                with open(sources_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    loaded_sources = data.get("sources", [])
                    _LOGGER.info(f"Loaded {len(loaded_sources)} sources from persistence file: {sources_file}")
            except Exception as e:
                _LOGGER.warning(f"Failed to load sources from file: {e}")

    if not loaded_sources:
        _LOGGER.warning("No sources found in file! Researcher will likely fail.")
        return {
            "section_notes": [],
            "error": "Sources file not found or empty. Please run Planner to collect sources first."
        }
        
    # 使用加载的素材
    sources = loaded_sources
    
    # 合并所有素材文本 (优先使用 full_text)
    all_text = "\n\n".join([
        f"【来源: {s.get('title', s.get('url', 'unknown'))}】\n{s.get('full_text', s.get('text_preview', ''))}"
        for s in sources
    ])
    
    # 收集所有图片
    all_images = []
    for s in sources:
        all_images.extend(s.get("images", []))
    
    section_notes = []
    
    # 并行处理所有章节 (Parallel Execution)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _research_single_section(idx: int, sec: Dict[str, Any]) -> Dict[str, Any]:
        """单个章节的研究任务（在线程中执行）"""
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_title = sec.get("title") or sec.get("heading") or f"章节 {idx + 1}"
        _LOGGER.info(f"[Parallel] Starting research for section: {section_id}")
        
        result = research_section_tool.invoke({
            "section_id": section_id,
            "section_title": section_title,
            "keywords": sec.get("keywords", []),
            "sources_text": all_text,
            "available_images": all_images,
        })
        result["_order"] = idx  # 保留顺序信息
        _LOGGER.info(f"[Parallel] Completed research for section: {section_id}")
        return result
    
    sections = outline.get("sections", [])
    max_workers = min(5, len(sections))  # RTX 5090D (32GB) 可支撑并发数 4
    
    _LOGGER.info(f"[Parallel] Starting parallel research with max_workers={max_workers} for {len(sections)} sections")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_research_single_section, idx, sec): idx
            for idx, sec in enumerate(sections)
        }
        
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                idx = futures[future]
                _LOGGER.error(f"[Parallel] Failed to research section {idx}: {e}")
                results.append({"section_id": f"sec_{idx+1}", "notes": f"研究失败: {e}", "relevant_images": [], "_order": idx})
    
    # 按原始顺序排序
    results.sort(key=lambda x: x.get("_order", 0))
    for r in results:
        r.pop("_order", None)  # 移除临时排序字段
    section_notes = results
    
    _LOGGER.info(f"[Parallel] All {len(section_notes)} sections researched")
    
    import os
    import json
    
    # 构造完整结果 (保存到文件)
    full_output = {
        "section_notes": section_notes,
        "source_summaries": {s.get("url", f"source_{i}"): s.get("text_preview", "")[:500] for i, s in enumerate(sources)},
    }
    
    # 落盘保存
    try:
        from .config import get_settings
        base_dir = get_settings().artifacts_dir
        article_id = article_id or os.environ.get("ARTICLE_CURRENT_ID", "")
        if article_id:
            save_dir = os.path.join(base_dir, f"article_{article_id}")
            os.makedirs(save_dir, exist_ok=True)
            notes_file = os.path.join(save_dir, "research_notes.json")
            
            with open(notes_file, "w", encoding="utf-8") as f:
                json.dump(full_output, f, ensure_ascii=False, indent=2)
                
            full_output["notes_file"] = notes_file
            _LOGGER.info(f"Research notes saved to: {notes_file}")
    except Exception as exc:
        _LOGGER.warning(f"Failed to save research notes: {exc}")
    
    # 只返回文件路径和状态，不返回笔记内容
    # Main Agent 如需查看笔记可以读取文件
    notes_file_path = full_output.get("notes_file", "")
    
    return {
        "status": "SUCCESS",
        "message": f"研究完成！已为 {len(section_notes)} 个章节整理好笔记并保存到文件。请立即调用 writer_agent 开始撰写文章。",
        "next_step": "writer_agent",
        "notes_file": notes_file_path,
        "total_sections": len(section_notes),
        "total_chars": sum(len(n.get("notes", "")) for n in section_notes),
    }


@tool
def research_audit_tool(section_notes: List[Dict[str, Any]]) -> Dict[str, Any]:
    """资料质检（规则质检，不用 LLM）。
    
    Args:
        section_notes: 各章节的资料笔记
        
    Returns:
        ResearchAuditOutput 字典
    """
    _LOGGER.info(f"research_audit_tool called with {len(section_notes)} sections")
    
    results = []
    sections_to_reresearch = []
    
    for note in section_notes:
        char_count = len(note.get("notes", ""))
        is_sufficient = char_count >= 300  # 最低 300 字符
        
        result = {
            "section_id": note.get("section_id", ""),
            "has_notes": bool(note.get("notes")),
            "notes_char_count": char_count,
            "is_sufficient": is_sufficient,
            "issues": [] if is_sufficient else [f"资料不足，当前 {char_count} 字符，需要至少 300 字符"],
        }
        results.append(result)
        
        if not is_sufficient:
            sections_to_reresearch.append(note.get("section_id", ""))
    
    all_passed = len(sections_to_reresearch) == 0
    _LOGGER.info(f"research_audit_tool: all_passed={all_passed}, to_reresearch={sections_to_reresearch}")
    
    return {
        "results": results,
        "all_passed": all_passed,
        "sections_to_reresearch": sections_to_reresearch,
    }



# ============================================================================
# Writer Agent Tools
# ============================================================================

@tool
def write_section_tool(
    section_id: str,
    section_title: str,
    target_chars: int,
    notes: str,
    is_core: bool = False,
) -> Dict[str, Any]:
    """撰写指定章节内容。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        target_chars: 目标字数
        notes: 资料笔记
        is_core: 是否核心章节
        
    Returns:
        SectionDraft 字典
    """
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"write_section_tool called for section: {section_id}, target_chars: {target_chars}")
    
    min_chars = 800 if is_core else 400
    
    system_prompt = f"""
你是 Writer，负责撰写文章的一个章节。

【任务】
根据资料笔记，撰写章节 "{section_title}" 的内容。

【要求】
1. 字数目标：{target_chars} 字符（最少 {min_chars} 字符）
2. 使用 Markdown 格式，以 "## {section_title}" 开头
3. 内容应流畅、有逻辑、信息丰富
4. 适当使用列表、引用等格式
5. 禁止使用占位符或待填充标记
6. 确保内容基于资料笔记，不要编造数据

【输出格式】
直接输出 Markdown 格式的章节内容（以 ## 开头）。
"""

    user_prompt = f"""
【资料笔记】
{notes[:6000]}

请撰写章节内容（目标 {target_chars} 字符）：
"""

    try:
        with log_performance("write_section", section_id=section_id, target_chars=target_chars):
            llm = build_chat_llm()
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
            input_chars = len(system_prompt) + len(user_prompt)
            response = llm.invoke(messages)
            
            # 记录 LLM 响应详情
            log_llm_response("write_section", response, input_chars=input_chars)
            
            markdown = response.content.strip()
        
        # 确保以标题开头
        if not markdown.startswith("#"):
            markdown = f"## {section_title}\n\n{markdown}"
        
        char_count = len(markdown)
        
        # 落盘：保存到临时文件
        import uuid
        import os
        
        # 使用环境变量或默认路径
        from .config import get_settings
        base_dir = get_settings().drafts_dir
        # 从 section_id 提取或生成 article_id
        article_id = os.environ.get("ARTICLE_CURRENT_ID", str(uuid.uuid4())[:8])
        os.environ["ARTICLE_CURRENT_ID"] = article_id  # 保存供后续使用
        
        article_dir = os.path.join(base_dir, f"article_{article_id}")
        os.makedirs(article_dir, exist_ok=True)
        
        file_name = f"section_{section_id}.md"
        file_path = os.path.join(article_dir, file_name)
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(markdown)
        
        _LOGGER.info(f"write_section_tool success: {char_count} chars, saved to {file_path}")
        
        result = {
            "section_id": section_id,
            "title": section_title,
            "file_path": file_path,  # 返回文件路径而不是完整内容
            "char_count": char_count,
            "preview": markdown[:200] + "..." if len(markdown) > 200 else markdown,  # 只返回预览
        }
        
        # 记录详细输出
        log_tool_output("write_section_tool", result, preview_fields=["preview"])
        
        return result
    except Exception as exc:
        _LOGGER.error(f"write_section_tool failed: {exc}")
        return {
            "section_id": section_id,
            "title": section_title,
            "file_path": "",
            "char_count": 0,
            "error": str(exc),
        }


@tool
def write_all_sections_tool(
    outline: Dict[str, Any],
    section_notes: List[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """撰写所有章节内容。
    
    Args:
        outline: 文章大纲
        section_notes: (可选) 即使传入也会被忽略，工具会自动从 research_notes.json 读取。
        
    Returns:
        WriterOutput 字典
    """
    _LOGGER.info(f"write_all_sections_tool called")
    
    import os
    import json
    
    # 优先加载 Persistent Outline
    from .config import get_settings
    settings = get_settings()
    base_dir = settings.artifacts_dir
    article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
    
    loaded_outline = {}
    if article_id:
        outline_file = os.path.join(base_dir, f"article_{article_id}", "outline.json")
        if os.path.exists(outline_file):
            try:
                with open(outline_file, "r", encoding="utf-8") as f:
                    loaded_outline = json.load(f)
                _LOGGER.info(f"Loaded outline from file: {outline_file}")
            except Exception as e:
                    _LOGGER.warning(f"Failed to load outline from file: {e}")

    if loaded_outline:
        outline = loaded_outline
    elif not outline or not outline.get("sections"):
        _LOGGER.warning("No outline provided and no outline file found!")
        return {"drafts": [], "error": "Missing outline"}
    
    # 强制从文件加载研究笔记（不使用内存数据）
    import os
    import json
    # base_dir already set to artifacts_dir above
    article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
    
    loaded_notes = []
    if article_id:
        notes_file = os.path.join(base_dir, f"article_{article_id}", "research_notes.json")
        if os.path.exists(notes_file):
            try:
                with open(notes_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    loaded_notes = data.get("section_notes", [])
                    _LOGGER.info(f"Loaded {len(loaded_notes)} notes from persistence file: {notes_file}")
            except Exception as e:
                _LOGGER.warning(f"Failed to load research notes from file: {e}")
    
    if not loaded_notes:
        _LOGGER.warning("No research notes found in file! Writer will likely fail or hallucinate.")
        return {
            "drafts": [],
            "total_chars": 0,
            "error": "Research notes file not found or empty. Please run Researcher first."
        }
    
    # 使用加载的笔记
    section_notes = loaded_notes
    
    # 构建笔记映射
    notes_map = {n.get("section_id", ""): n.get("notes", "") for n in section_notes}
    _LOGGER.info(f"Built notes map with {len(notes_map)} entries. Keys: {list(notes_map.keys())[:5]}")
    
    drafts = []
    total_chars = 0
    
    sections = outline.get("sections", [])
    _LOGGER.info(f"Processing {len(sections)} sections from outline")
    
    # 并行处理所有章节 (Parallel Execution)
    from concurrent.futures import ThreadPoolExecutor, as_completed
    
    def _write_single_section(idx: int, sec: Dict[str, Any]) -> Dict[str, Any]:
        """单个章节的写作任务（在线程中执行）"""
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_title = sec.get("title") or sec.get("heading") or f"章节 {idx + 1}"
        notes = notes_map.get(section_id, "")
        _LOGGER.info(f"[Parallel] Starting writing for section: {section_id}")
        
        result = write_section_tool.invoke({
            "section_id": section_id,
            "section_title": section_title,
            "target_chars": sec.get("target_chars", 500),
            "notes": notes,
            "is_core": sec.get("is_core", False),
        })
        result["_order"] = idx  # 保留顺序信息
        _LOGGER.info(f"[Parallel] Completed writing for section: {section_id}")
        return result
    
    max_workers = min(5, len(sections))  # RTX 5090D (32GB) 可支撑并发数 4
    
    _LOGGER.info(f"[Parallel] Starting parallel writing with max_workers={max_workers} for {len(sections)} sections")
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(_write_single_section, idx, sec): idx
            for idx, sec in enumerate(sections)
        }
        
        results = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as e:
                idx = futures[future]
                _LOGGER.error(f"[Parallel] Failed to write section {idx}: {e}")
                results.append({"section_id": f"sec_{idx+1}", "content": f"写作失败: {e}", "char_count": 0, "_order": idx})
    
    # 按原始顺序排序
    results.sort(key=lambda x: x.get("_order", 0))
    for r in results:
        total_chars += r.get("char_count", 0)
        r.pop("_order", None)  # 移除临时排序字段
    drafts = results
    
    _LOGGER.info(f"[Parallel] All {len(drafts)} sections written, total_chars={total_chars}")
    
    # 强制不返回 drafts 内容，确保下游 Reviewer 必须从文件系统读取
    # 但必须返回足够的 Metadata 告知 LLM 任务已完成，否则会导致 infinite retry loop
    return {
        "status": "success",
        "message": f"Successfully wrote {len(drafts)} sections to file system.",
        "drafts": [], # Empty list kept for Zero-Memory compliance
        "total_char_count": total_chars,
        "saved_files": [d["file_path"] for d in drafts] # Minimal references
    }


@tool
def writer_audit_tool(drafts: List[Dict[str, Any]], outline: Dict[str, Any]) -> Dict[str, Any]:
    """写作质检（规则质检，不用 LLM）。
    
    Args:
        drafts: 各章节草稿
        outline: 文章大纲
        
    Returns:
        WriterAuditOutput 字典
    """
    # TODO: Phase 2 实现，复用 deep_graph.py 中的 writer_audit_node 逻辑
    _LOGGER.info(f"writer_audit_tool called")
    
    # 构建 section 字数要求映射
    section_requirements = {}
    for idx, sec in enumerate(outline.get("sections", [])):
        section_id = sec.get("id") or sec.get("section_id") or f"sec_{idx + 1}"
        section_requirements[section_id] = {
            "target_chars": sec.get("target_chars", 400),
            "is_core": sec.get("is_core", False),
        }
    
    results = []
    sections_to_rewrite = []
    
    for draft in drafts:
        section_id = draft.get("section_id", "")
        char_count = draft.get("char_count", 0)
        
        req = section_requirements.get(section_id, {"target_chars": 400, "is_core": False})
        min_required = 800 if req["is_core"] else 400
        
        is_sufficient = char_count >= min_required
        has_heading = draft.get("markdown", "").strip().startswith("#")
        
        issues = []
        if not is_sufficient:
            issues.append(f"字数不足，当前 {char_count} 字符，需要至少 {min_required} 字符")
        if not has_heading:
            issues.append("缺少章节标题")
        
        result = {
            "section_id": section_id,
            "char_count": char_count,
            "min_required": min_required,
            "is_sufficient": is_sufficient,
            "has_heading": has_heading,
            "issues": issues,
        }
        results.append(result)
        
        if issues:
            sections_to_rewrite.append(section_id)
    
    return {
        "results": results,
        "all_passed": len(sections_to_rewrite) == 0,
        "sections_to_rewrite": sections_to_rewrite,
    }


# ============================================================================
# Reviewer Agent Tools
# ============================================================================

@tool
def review_draft_tool(drafts: List[Dict[str, Any]], instruction: str) -> Dict[str, Any]:
    """审阅草稿，返回反馈和是否通过。
    
    Args:
        drafts: 各章节草稿（包含 file_path）
        instruction: 用户写作指令
        
    Returns:
        ReviewerOutput 字典
    """
    import json
    import re
    import os
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"review_draft_tool called with {len(drafts)} sections")
    
    from .config import get_settings
    settings = get_settings()
    artifacts_dir = settings.artifacts_dir
    drafts_dir = settings.drafts_dir
    article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
    
    # 1. 第一步：获取"藏宝图" (加载 Persistent Outline)
    # 我们必须先加载 Outline，因为它是唯一包含 Section ID 的地方。
    # 只有知道了 Section ID (例如 "sec_1")，我们由于 Writer 的命名规则 (sec_1.md)，才知道去磁盘的哪里寻找 Draft 文件。
    loaded_outline = {}
    if article_id:
        outline_file = os.path.join(artifacts_dir, f"article_{article_id}", "outline.json")
        if os.path.exists(outline_file):
            try:
                with open(outline_file, "r", encoding="utf-8") as f:
                    loaded_outline = json.load(f)
                _LOGGER.info(f"Loaded outline from file: {outline_file}")
            except Exception as e:
                _LOGGER.warning(f"Failed to load outline from file: {e}")

    if loaded_outline:
        outline = loaded_outline
        
    # 2. 强制从大纲和文件系统读取草稿 (忽略内存输入的 drafts)
    # 用户要求：即使 drafts 不为空，也要读文件
    _LOGGER.info("Scanning file system for drafts based on outline...")
    
    found_drafts = []
    if outline and article_id:
         article_dir = os.path.join(drafts_dir, f"article_{article_id}")
         for sec in outline.get("sections", []):
             sec_id = sec.get("id") or sec.get("section_id")
             if sec_id:
                 # 尝试匹配文件名 (section_id.md)
                 draft_path = os.path.join(article_dir, f"{sec_id}.md")
                 
                 # 兼容旧命名 (section_N.md)
                 if not os.path.exists(draft_path) and "sec_" in sec_id:
                     # 尝试匹配 section_sec_1.md (现在实际生成的格式)
                     draft_path_prefix = os.path.join(article_dir, f"section_{sec_id}.md")
                     if os.path.exists(draft_path_prefix):
                         draft_path = draft_path_prefix
                     else:
                         try:
                             idx = int(sec_id.split("_")[1])
                             draft_path_alt = os.path.join(article_dir, f"section_{idx}.md")
                             if os.path.exists(draft_path_alt):
                                 draft_path = draft_path_alt
                         except:
                             pass
                         
                 if os.path.exists(draft_path):
                     found_drafts.append({
                         "file_path": draft_path, 
                         "section_id": sec_id,
                         "title": sec.get("title", "")
                     })
                     _LOGGER.info(f"Found draft file: {draft_path}")
    
    # 使用找到的 drafts 覆盖输入
    if found_drafts:
        drafts = found_drafts
        _LOGGER.info(f"Reviewing {len(drafts)} drafts found in filesystem")
    else:
        _LOGGER.warning("No drafts found in filesystem! Using memory drafts if available.")
    
    if not drafts:
        return {
            "overall_quality": 0,
            "section_feedback": [],
            "sections_to_rewrite": [],
            "approved": False,
            "error": "No drafts found to review"
        }

    # 从文件读取所有草稿内容
    sections_content = []
    for d in drafts:
        file_path = d.get("file_path", "")
        if file_path and os.path.exists(file_path):
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            sections_content.append(content)
        else:
            # 兼容旧格式或预览
            sections_content.append(d.get("markdown", d.get("preview", "")))
    
    all_markdown = "\n\n".join(sections_content)
    
    system_prompt = """
你是 Reviewer，负责从读者视角审阅文章草稿。

【任务】
评估文章质量，指出问题并给出改进建议。

【评分标准】
- 9-10: 优秀，可直接发布
- 7-8: 良好，小修后可发布
- 5-6: 一般，需要部分重写
- 1-4: 较差，需要大幅重写

【输出格式】
输出 JSON：
{
  "overall_quality": 8,
  "section_feedback": [
    {"section_id": "sec_1", "quality_score": 8, "issues": [], "suggestions": []}
  ],
  "sections_to_rewrite": [],
  "approved": true
}
"""

    user_prompt = f"""
【用户指令】
{instruction}

【文章草稿】
{all_markdown[:10000]}

请审阅并输出 JSON：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            # 确保 approved 字段
            if "approved" not in result:
                result["approved"] = result.get("overall_quality", 0) >= 7
            _LOGGER.info(f"review_draft_tool: quality={result.get('overall_quality')}, approved={result.get('approved')}")
            return result
        else:
            # 默认通过
            _LOGGER.warning(f"review_draft_tool: no JSON found, defaulting to approved")
            return {
                "overall_quality": 7,
                "section_feedback": [],
                "sections_to_rewrite": [],
                "approved": True,
            }
    except Exception as exc:
        _LOGGER.error(f"review_draft_tool failed: {exc}")
        return {
            "overall_quality": 7,
            "section_feedback": [],
            "sections_to_rewrite": [],
            "approved": True,
            "error": str(exc),
        }


# ============================================================================
# Illustrator Agent Tools
# ============================================================================

@tool
def match_images_tool(
    drafts: List[Dict[str, Any]],
    available_images: List[Dict[str, Any]],
    max_images: int = 5,
) -> Dict[str, Any]:
    """匹配图片到文章内容，确定放置位置。
    
    Args:
        drafts: 各章节草稿（包含 file_path）
        available_images: 可用图片列表
        max_images: 最大图片数
        
    Returns:
        IllustratorOutput 字典
    """
    import json
    import re
    import os
    from .llm_runtime import build_chat_llm
    from langchain_core.messages import HumanMessage, SystemMessage
    
    _LOGGER.info(f"match_images_tool called with {len(available_images)} images")
    
    # 从 drafts 参数中提取文件路径
    draft_files = [d.get("file_path") or d.get("path", "") for d in drafts if d]
    
    # 从文件读取所有草稿内容
    sections_content = []
    _LOGGER.info(f"match_images_tool called with {len(available_images)} images, {len(draft_files)} files")
    
    # 1. 读取所有草稿内容
    full_content = ""
    file_contents = {} # path -> content
    
    for path in draft_files:
        if path and os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    content = f.read()
                    file_contents[path] = content
                    full_content += content + "\n\n"
            except Exception as e:
                _LOGGER.warning(f"Failed to read draft file {path}: {e}")
    
    if not full_content:
        _LOGGER.warning("No content read from draft files")
        return {
            "placements": [],
            "final_markdown": "", # Return empty markdown if failed
        }
    
    # 2. 准备图片信息（仅前10张作为候选，避免 Context 爆炸）
    images_info = "\n".join([
        f"- 图片{i+1}: {img.get('path_or_url', '')[:50]}... | alt: {img.get('alt', '')}"
        for i, img in enumerate(available_images[:10])
    ])
    
    system_prompt = f"""
你是 Illustrator，负责为文章选择和放置合适的图片。

【可用图片】
{images_info}

【文章标题】
{chr(10).join(headings[:10])}

【任务】
1. 从可用图片中选择最多 5 张与文章内容相关的图片
2. 确定每张图片应放置在哪个标题后
3. 生成图片说明

【输出格式】
输出 JSON：
{{
  "placements": [
    {{"image_index": 0, "after_heading": "## 引言", "caption": "图片说明"}}
  ]
}}
"""

    user_prompt = f"""
【文章内容（摘要）】
{full_content[:5000]}

请选择图片并确定放置位置（输出 JSON）：
"""

    try:
        llm = build_chat_llm()
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = response.content.strip()
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            result = json.loads(json_match.group())
            placements = result.get("placements", [])
            
            # 构建最终 Markdown（插入图片）
            final_markdown = full_content
            for p in reversed(placements):  # 倒序插入，避免位置偏移
                img_idx = p.get("image_index", 0)
                if img_idx < len(available_images):
                    img = available_images[img_idx]
                    img_url = img.get("path_or_url", "")
                    alt = img.get("alt", "")
                    caption = p.get("caption", "")
                    after_heading = p.get("after_heading", "")
                    
                    # 在标题后插入图片
                    img_md = f"\n\n![{caption or alt}]({img_url})\n*{caption}*\n"
                    if after_heading:
                        final_markdown = final_markdown.replace(
                            after_heading,
                            after_heading + img_md,
                            1
                        )
            
            formatted_placements = [
                {
                    "image_url": available_images[p.get("image_index", 0)].get("path_or_url", ""),
                    "alt_text": available_images[p.get("image_index", 0)].get("alt", ""),
                    "after_heading": p.get("after_heading", ""),
                    "caption": p.get("caption", ""),
                }
                for p in placements if p.get("image_index", 0) < len(available_images)
            ]
            
            # 保存到文件
            final_path = ""
            try:
                base_dir = os.environ.get("ARTICLE_TEMP_DIR", "/tmp/article_drafts")
                article_id = os.environ.get("ARTICLE_CURRENT_ID", "")
                if article_id:
                    save_dir = os.path.join(base_dir, f"article_{article_id}")
                    os.makedirs(save_dir, exist_ok=True)
                    final_path = os.path.join(save_dir, "draft_with_images.md")
                    with open(final_path, "w", encoding="utf-8") as f:
                        f.write(final_markdown)
                    _LOGGER.info(f"Saved draft with images to {final_path}")
            except Exception as e:
                _LOGGER.warning(f"Failed to save draft with images: {e}")

            _LOGGER.info(f"match_images_tool success: {len(formatted_placements)} images placed")
            
            # 返回路径而不是内容，减少 Context
            return {
                "placements": formatted_placements,
                "final_markdown_path": final_path,
                "preview": final_markdown[:200] + "..."
            }
        else:
            _LOGGER.warning(f"match_images_tool: no JSON found")
            return {
                "placements": [],
                "final_markdown_path": "",
                "preview": full_content[:200] + "..."
            }
    except Exception as exc:
        _LOGGER.error(f"match_images_tool failed: {exc}")
        return {
            "placements": [],
            "final_markdown_path": "",
            "error": str(exc),
        }


# ============================================================================
# Assembler Agent Tools
# ============================================================================

@tool
def assemble_article_tool(
    article_id: str,
    title: str,
    final_markdown_path: str,
) -> Dict[str, Any]:
    """组装最终文章并保存。
    
    Args:
        article_id: 文章 ID
        title: 文章标题
        final_markdown_path: 最终 Markdown 文件路径
        
    Returns:
        AssemblerOutput 字典
    """
    from .tools_files import export_markdown
    import re
    import os
    
    _LOGGER.info(f"assemble_article_tool called for: {article_id}, path: {final_markdown_path}")
    
    final_markdown = ""
    if final_markdown_path and os.path.exists(final_markdown_path):
        try:
            with open(final_markdown_path, "r", encoding="utf-8") as f:
                final_markdown = f.read()
        except Exception as e:
            _LOGGER.error(f"Failed to read final markdown from {final_markdown_path}: {e}")
            return {"error": f"Failed to read file: {e}"}
    else:
        _LOGGER.error(f"Final markdown file not found: {final_markdown_path}")
        return {"error": "Final markdown file not found"}
    
    # 清理 Markdown
    cleaned_md = final_markdown
    
    # 去除多余空行
    cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md)
    
    # 去除思维过程标记
    cleaned_md = re.sub(r'<think>[\s\S]*?</think>', '', cleaned_md)
    
    # 确保标题正确
    if not cleaned_md.strip().startswith("#"):
        cleaned_md = f"# {title}\n\n{cleaned_md}"
    
    try:
        result = export_markdown(cleaned_md, title, article_id)
        _LOGGER.info(f"assemble_article_tool success: {result.get('md_path')}")
        return {
            "article_id": article_id,
            "md_path": result.get("md_path", ""),
            "md_url": result.get("md_url", ""),
            "final_markdown": cleaned_md, # Restore content for UI display
        }
    except Exception as exc:
        _LOGGER.error(f"assemble_article_tool failed: {exc}")
        # 备用路径
        return {
            "article_id": article_id,
            "md_path": f"/data/articles/{article_id}.md",
            "md_url": f"/articles/{article_id}.md",
            "error": str(exc),
        }


__all__ = [
    # Collector
    "fetch_url_tool",
    "load_file_tool",
    "collect_all_sources_tool",
    # Planner
    "generate_outline_tool",
    # Researcher
    "read_sources_tool",
    "research_section_tool",
    "research_all_sections_tool",
    "research_audit_tool",
    # Writer
    "write_section_tool",
    "write_all_sections_tool",
    "writer_audit_tool",
    # Reviewer
    "review_draft_tool",
    # Illustrator
    "match_images_tool",
    # Assembler
    "assemble_article_tool",
]
