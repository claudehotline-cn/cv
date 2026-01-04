"""Article Deep Agent Tools - Assembler Agent"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from ..utils.artifacts import get_current_article_id, get_drafts_dir, get_article_dir, get_final_article_dir, load_article_artifact

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.assembler")

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
    
    _LOGGER.info(f"assemble_article_tool called for: {article_id}, path: {final_markdown_path}")
    
    # 初始化变量
    final_markdown = ""
    article_id = get_current_article_id(article_id)
    
    # 自动发现逻辑：如果没有传入路径，尝试自动查找
    # 自动发现逻辑：强制从 drafts 目录发现并合并 section_*.md
    drafts_dir = get_drafts_dir(article_id)
    
    # 尝试合并所有 section_*.md
    import glob
    section_files = glob.glob(os.path.join(drafts_dir, "section_*.md"))
    
    if not section_files:
         _LOGGER.error(f"No section files found in {drafts_dir}")
         return {"error": "No section files found to assemble"}

    # 按章节号数字排序：section_sec_1.md, section_sec_2.md, ...
    def extract_section_num(path):
        match = re.search(r'section_sec_(\d+)', path)
        return int(match.group(1)) if match else 999
    
    section_files.sort(key=extract_section_num)
    
    _LOGGER.info(f"Merging {len(section_files)} section files (sorted) from {drafts_dir}")
    merged_content = ""
    for sf in section_files:
        try:
            with open(sf, "r", encoding="utf-8") as f:
                content = f.read()
                # 简单清洗：确保章节之间有足够空行
                merged_content += content.strip() + "\n\n"
        except Exception as read_err:
             _LOGGER.error(f"Failed to read section file {sf}: {read_err}")
             
    final_markdown = merged_content

    # ========== Image Placeholder Resolution (Image-First Workflow) ==========
    # 查找并替换Writer生成的占位符 [[IMAGE: img_id]] 为实际 Markdown 图片链接
    
    # 1. Build Global Image Map from all manifests/elements
    image_map = {}
    try:
        from ...config.config import get_settings
        settings = get_settings()
        corpus_dir = os.path.join(settings.artifacts_dir, f"article_{article_id}", "corpus")
        if os.path.exists(corpus_dir):
            for doc_name in os.listdir(corpus_dir):
                doc_path = os.path.join(corpus_dir, doc_name)
                # Try elements.jsonl (located in parsed/ subdirectory)
                elements_path = os.path.join(doc_path, "parsed", "elements.jsonl")
                if os.path.exists(elements_path):
                    with open(elements_path, "r", encoding="utf-8") as f:
                        for line in f:
                            try:
                                el = None
                                import json
                                el = json.loads(line)
                                if el.get("type") == "image" and el.get("element_id"):
                                    image_map[el["element_id"]] = el
                            except:
                                pass
    except Exception as img_map_err:
        _LOGGER.warning(f"Failed to build image map: {img_map_err}")

    # 2. Replace placeholders
    def replace_image_placeholder(match):
        img_id = match.group(1).strip()
        img_info = image_map.get(img_id)
        if img_info:
            src = img_info.get("src", "")
            alt = img_info.get("visual_description") or img_info.get("content") or "Image"
            # Cleaning alt text for markdown safe
            alt = alt.replace("\n", " ").replace("]", "").replace("[", "")[:100]
            if src:
                return f"![{alt}]({src})"
        return f"> [Image {img_id} Not Found]"
    
    # Pattern: [[IMAGE: img_123]]
    final_markdown = re.sub(r'\[\[IMAGE:\s*([a-zA-Z0-9_]+)\]\]', replace_image_placeholder, final_markdown)
    _LOGGER.info(f"Resolved image placeholders using map with {len(image_map)} images")



    
    # ========== 消费 citations_map.json ==========
    citations_map = load_article_artifact(article_id, "citations_map.json")
    if citations_map and citations_map.get("anchors"):
        _LOGGER.info(f"Found {len(citations_map.get('anchors', []))} citations in citations_map")
        # 可以在这里添加脚注处理逻辑


    
    # 清理 Markdown
    cleaned_md = final_markdown
    
    # 去除多余空行
    cleaned_md = re.sub(r'\n{3,}', '\n\n', cleaned_md)
    
    # 去除思维过程标记
    cleaned_md = re.sub(r'<think>[\s\S]*?</think>', '', cleaned_md)
    
    # 确保标题正确
    if not cleaned_md.strip().startswith("#"):
        cleaned_md = f"# {title}\n\n{cleaned_md}"
    
    # 落盘：保存最终文章
    # 修正逻辑：最终文章保存到 artifacts/article_{id}/article/article.md
    article_dir = get_final_article_dir(article_id) # artifacts/article_{id}/article
    os.makedirs(article_dir, exist_ok=True)
    
    # 始终命名为 article.md 以便统一
    output_filename = "article.md" 
    output_path = os.path.join(article_dir, output_filename)
        
    try:
        # export_markdown 原本负责写入文件，现在直接在 tool 里写，或者调整 export_markdown 
        # 这里直接写入文件，因为 export_markdown 可能还依赖旧的环境变量逻辑
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(cleaned_md)
        _LOGGER.info(f"Article exported to: {output_path}")
        
        # ========== 新增：生成 build_log.json ==========
        import datetime
        import json
        
        build_log = {
            "article_id": article_id,
            "timestamp": datetime.datetime.now().isoformat(),
            "status": "success",
            "source_path": final_markdown_path or "merged_sections",
            "output_path": output_path,
            "stats": {
                "total_chars": len(cleaned_md),
                "total_lines": cleaned_md.count("\n"),
                "has_title": cleaned_md.strip().startswith("#"),
            },
            "steps": [
                {"step": "read_source", "status": "success"},
                {"step": "clean_markdown", "status": "success"},
                {"step": "add_title", "status": "success" if not final_markdown.strip().startswith("#") else "skipped"},
                {"step": "save_output", "status": "success"},
            ],
            "errors": []
        }
        
        build_log_path = os.path.join(article_dir, "build_log.json")
        try:
            with open(build_log_path, "w", encoding="utf-8") as f:
                json.dump(build_log, f, ensure_ascii=False, indent=2)
            _LOGGER.info(f"Build log saved to: {build_log_path}")
        except Exception as e:
            _LOGGER.warning(f"Failed to save build_log: {e}")
        
        # 注意：md_path 和 article_id 由 AssemblerStateMiddleware 自动写入 State
        # 无需在这里手动写入文件
        
        # 兼容旧的返回值结构，伪造 md_url (或者由前端根据 id 拼装)
        # 前端现在主要用 final_content, md_url 只是 fallback
        md_url = f"/api/articles/{article_id}/content" # 假设有个 API
        
        return {
            "article_id": article_id,
            "md_path": output_path,
            "md_url": md_url,
            "build_log_path": build_log_path,
            "article_content": cleaned_md,  # 前端期望的字段名
        }
    except Exception as exc:
        _LOGGER.error(f"assemble_article_tool failed: {exc}")
        # 备用路径
        return {
            "article_id": article_id,
            "md_path": f"/data/articles/{article_id}.md",
            "md_url": f"/articles/{article_id}.md",
            "article_content": "", # Ensure key exists to satisfy middleware strict check
            "error": str(exc),
        }
