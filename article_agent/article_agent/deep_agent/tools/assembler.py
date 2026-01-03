"""Article Deep Agent Tools - Assembler Agent"""
from __future__ import annotations

import logging
import os
import re
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from ..utils.artifacts import get_current_article_id, get_drafts_dir, get_article_dir, get_final_article_dir

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
    if not final_markdown_path or not os.path.exists(final_markdown_path):
        drafts_dir = get_drafts_dir(article_id)
        candidate_path = os.path.join(drafts_dir, "draft_with_images.md") # Illustrator's output
        
        if os.path.exists(candidate_path):
            final_markdown_path = candidate_path
            _LOGGER.info(f"Auto-discovered final markdown in drafts: {final_markdown_path}")
        else:
            # 其次查找 artifacts 根目录 (兼容旧数据)
            artifacts_dir = get_article_dir(article_id)
            candidate_path_old = os.path.join(artifacts_dir, "draft_with_images.md")
            if os.path.exists(candidate_path_old):
                final_markdown_path = candidate_path_old
                _LOGGER.info(f"Auto-discovered final markdown in artifacts (legacy): {final_markdown_path}")
            else:
                # 如果没有 draft_with_images.md，尝试合并所有 section_*.md
                import glob
                section_files = glob.glob(os.path.join(drafts_dir, "section_*.md"))
                # 按章节号数字排序：section_sec_1.md, section_sec_2.md, ...
                def extract_section_num(path):
                    match = re.search(r'section_sec_(\d+)', path)
                    return int(match.group(1)) if match else 999
                section_files.sort(key=extract_section_num)
                if section_files:
                    _LOGGER.info(f"No draft_with_images.md found, merging {len(section_files)} section files (sorted)")
                    merged_content = ""
                    for sf in section_files:
                        with open(sf, "r", encoding="utf-8") as f:
                            merged_content += f.read() + "\n\n"
                    # 直接使用合并内容，跳过文件读取
                    final_markdown = merged_content
    
    if not final_markdown:
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

    # ========== NEW: 消费 illustration_plan.json ==========
    import json
    from ..utils.artifacts import load_article_artifact
    
    illustration_plan = None
    # 尝试从 assets 目录读取
    assets_dir = os.path.join(get_article_dir(article_id), "assets")
    plan_path = os.path.join(assets_dir, "illustration_plan.json")
    
    if os.path.exists(plan_path):
        try:
            with open(plan_path, "r", encoding="utf-8") as f:
                illustration_plan = json.load(f)
            _LOGGER.info(f"Loaded illustration_plan.json with {len(illustration_plan.get('figures', []))} figures")
        except Exception as e:
            _LOGGER.warning(f"Failed to load illustration_plan: {e}")
    
    # 如果有 illustration_plan 且 draft 中还没有插图，则应用
    if illustration_plan and "figures" in illustration_plan:
        figures = illustration_plan.get("figures", [])
        if figures and "<figure" not in final_markdown:
            _LOGGER.info(f"Applying {len(figures)} figures from illustration_plan")
            lines = final_markdown.split('\n')
            
            # 倒序插入以避免索引偏移
            insertion_ops = []
            for fig in figures:
                anchor = fig.get("insert_after_anchor", "")
                caption = fig.get("caption", "")
                figure_id = fig.get("figure_id", "")
                
                if not anchor:
                    continue
                
                # 找到锚点位置
                for i, line in enumerate(lines):
                    if anchor in line or line.strip() == anchor:
                        # 构建图片 HTML
                        src = fig.get("src", "")
                        # 尝试将绝对路径转换为相对路径 (如果可能)
                        # 这里简单处理，如果 src 是绝对路径且存在，保持原样；如果是相对路径，假设在 assets
                        
                        img_tag = f'<img src="{src}" alt="{caption}" style="max-width: 100%; border-radius: 8px; box-shadow: 0 4px 6px rgba(0,0,0,0.1);">' if src else f"<!-- Missing image src for {figure_id} -->"
                        
                        fig_html = f'''
<figure style="text-align: center; margin: 20px 0;">
  {img_tag}
  <figcaption style="color: #666; font-size: 0.9em; margin-top: 8px;"><strong>{figure_id}</strong> {caption}</figcaption>
</figure>
'''
                        insertion_ops.append((i + 1, fig_html))
                        break
            
            # 倒序插入
            insertion_ops.sort(key=lambda x: x[0], reverse=True)
            for idx, content in insertion_ops:
                lines.insert(idx, content)
            
            final_markdown = '\n'.join(lines)
            _LOGGER.info(f"Inserted {len(insertion_ops)} figures into draft")
    
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
