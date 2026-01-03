"""Article Deep Agent Tools - Illustrator Agent"""
from __future__ import annotations

import logging
import os
import json
import re
import base64
import requests
import mimetypes
from typing import Any, Dict, List, Optional
from langchain_core.tools import tool
from langchain_core.messages import HumanMessage, SystemMessage

from ...config.llm_runtime import build_chat_llm, build_vlm_client, extract_text_content
from ..utils.logging.tools_logging import log_performance, log_llm_response
from ..utils.artifacts import (
    get_current_article_id, 
    load_article_artifact, 
    get_drafts_dir,
    save_article_artifact # though illustrator saves raw md, we might need path helpers
)
from .prompts import ILLUSTRATOR_MATCH_SYSTEM_PROMPT, ILLUSTRATOR_MATCH_USER_PROMPT

_LOGGER = logging.getLogger("article_agent.deep_agent.tools.illustrator")

def _encode_image(path_or_url: str) -> Optional[str]:
    """将图片（路径或 URL）转换为 Base64 Data URI。
    
    由于 Ollama 运行在宿主机，无法直接访问容器内的文件，
    因此必须将图片转换为 Base64 字符串传递。
    """
    if not path_or_url:
        return None
        
    try:
        image_data = None
        mime_type = None
        
        # 1. Handle URL
        if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
            # Retry logic with exponential backoff
            max_retries = 3
            retry_delay = 2  # seconds
            
            for attempt in range(max_retries):
                try:
                    # Set timeout to avoid hanging, add User-Agent to avoid 403
                    headers = {
                        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
                    }
                    response = requests.get(path_or_url, timeout=15, headers=headers)
                    response.raise_for_status()
                    image_data = response.content
                    # Try to guess mime type from header or url
                    content_type = response.headers.get('Content-Type')
                    if content_type:
                        mime_type = content_type
                    else:
                        mime_type, _ = mimetypes.guess_type(path_or_url)
                    break  # Success, exit retry loop
                except Exception as e:
                    if attempt < max_retries - 1:
                        _LOGGER.warning(f"Image download attempt {attempt+1}/{max_retries} failed: {path_or_url}, retrying in {retry_delay}s...")
                        import time
                        time.sleep(retry_delay)
                        retry_delay *= 2  # Exponential backoff
                    else:
                        _LOGGER.warning(f"Failed to download image after {max_retries} attempts: {path_or_url}, error: {e}")
                        return None
                
        # 2. Handle Local File
        elif os.path.exists(path_or_url):
            try:
                with open(path_or_url, "rb") as f:
                    image_data = f.read()
                mime_type, _ = mimetypes.guess_type(path_or_url)
            except Exception as e:
                _LOGGER.warning(f"Failed to read local image: {path_or_url}, error: {e}")
                return None
        else:
            _LOGGER.warning(f"Image path not found: {path_or_url}")
            return None

        if not mime_type:
            mime_type = "image/jpeg" # Default fallback
        
        # 处理 SVG：转换为 PNG（VLM 不支持矢量格式）
        if mime_type == "image/svg+xml" or path_or_url.lower().endswith('.svg'):
            try:
                import cairosvg
                png_data = cairosvg.svg2png(bytestring=image_data)
                image_data = png_data
                mime_type = "image/png"
                _LOGGER.info(f"Converted SVG to PNG: {path_or_url}")
            except ImportError:
                _LOGGER.warning(f"cairosvg not installed, cannot convert SVG: {path_or_url}")
                return None
            except Exception as e:
                _LOGGER.warning(f"Failed to convert SVG to PNG: {path_or_url}, error: {e}")
                return None
            
        base64_data = base64.b64encode(image_data).decode('utf-8')
        return f"data:{mime_type};base64,{base64_data}"
        
    except Exception as e:
        _LOGGER.error(f"Error encoding image {path_or_url}: {e}")
        return None

@tool
def match_images_tool(
    drafts: List[Dict[str, Any]],
    max_images: int = 5,
) -> Dict[str, Any]:
    """匹配图片到文章内容，确定放置位置。
    
    Args:
        drafts: 各章节草稿（包含 file_path）
        max_images: 最大图片数
        
    Returns:
        IllustratorOutput 字典
    """
    available_images = []
    
    _LOGGER.info(f"match_images_tool called")
    
    # 从 corpus 目录下的 elements.jsonl 加载图片
    # (Ingest Agent 将图片保存到 corpus/{doc_id}/parsed/elements.jsonl)
    article_id = get_current_article_id()
    if article_id:
        from ...config.config import get_article_dir
        import glob
        import json
        
        article_dir = get_article_dir(article_id)
        corpus_dir = os.path.join(article_dir, "corpus")
        
        # 查找所有 elements.jsonl 文件
        elements_files = glob.glob(os.path.join(corpus_dir, "*/parsed/elements.jsonl"))
        
        for elements_file in elements_files:
            try:
                with open(elements_file, "r", encoding="utf-8") as f:
                    for line in f:
                        if line.strip():
                            elem = json.loads(line)
                            if elem.get("type") == "image" and elem.get("src"):
                                available_images.append({
                                    "src": elem.get("src"),
                                    "alt": elem.get("content", ""),
                                    "element_id": elem.get("element_id", ""),
                                    "page": elem.get("page", 0)
                                })
            except Exception as e:
                _LOGGER.warning(f"Failed to load images from {elements_file}: {e}")
        
        _LOGGER.info(f"Loaded {len(available_images)} images from {len(elements_files)} elements.jsonl files")
        
    if not available_images:
        _LOGGER.warning("No images loaded from elements.jsonl!")
    
    _LOGGER.info(f"match_images_tool: article_id={article_id}, input drafts count={len(drafts) if drafts else 0}")
    
    # 强制使用自动发现逻辑，忽略 LLM 可能传入的错误路径
    # 因为 LLM 经常传入不存在的路径如 /sec/xxx/sec_1.md
    # 强制使用自动发现逻辑，忽略 LLM 可能传入的错误路径
    # 因为 LLM 经常传入不存在的路径如 /sec/xxx/sec_1.md
    if article_id:
        import glob
        drafts_dir = get_drafts_dir(article_id)
        _LOGGER.info(f"match_images_tool: Auto-discovering in {drafts_dir}, exists={os.path.exists(drafts_dir)}")
        if os.path.exists(drafts_dir):
            draft_files_found = glob.glob(os.path.join(drafts_dir, "section_*.md"))
            # 按章节号排序：section_sec_1.md, section_sec_2.md, ...
            # 提取 sec_N 中的 N 进行数字排序
            import re
            def extract_section_num(path):
                match = re.search(r'section_sec_(\d+)', path)
                return int(match.group(1)) if match else 999
            draft_files_found.sort(key=extract_section_num)
            # 覆盖 LLM 传入的可能错误的 drafts
            drafts = [{"file_path": f} for f in draft_files_found]
            _LOGGER.info(f"Auto-discovered {len(drafts)} drafts in {drafts_dir} (sorted): {draft_files_found[:3]}")
        else:
            _LOGGER.warning(f"Drafts directory not found: {drafts_dir}")
    
    # 从 drafts 参数中提取文件路径
    draft_files = [d.get("file_path") or d.get("path", "") for d in drafts if d]
    
    # 从文件读取所有草稿内容
    sections_content = []
    _LOGGER.info(f"match_images_tool processing {len(draft_files)} draft files: {draft_files[:3]}")
    
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
    
    # 2. 图片去重与预处理
    # elements.jsonl 可能包含重复条目（如有无 src 的版本），需要去重并保留有 src 的版本
    unique_images_map = {}
    for img in available_images:
        eid = img.get("element_id")
        if not eid:
            continue
        
        has_src = bool(img.get("src") or img.get("path_or_url"))
        
        # 如果 ID 不存在，或者新条目有 src 而旧条目没有，则更新
        if eid not in unique_images_map:
            unique_images_map[eid] = img
        elif has_src and not (unique_images_map[eid].get("src") or unique_images_map[eid].get("path_or_url")):
            unique_images_map[eid] = img
            
    # 使用去重后的列表
    deduplicated_images = list(unique_images_map.values())
    _LOGGER.info(f"Deduplicated images: {len(available_images)} -> {len(deduplicated_images)}")
    
    vlm = build_vlm_client(task_name="illustrator_vlm")
    images_with_desc = []
    
    for i, img in enumerate(deduplicated_images):  # 分析去重后的图片
        # 优先使用 src (统一格式)，兼容 path_or_url
        img_url = img.get("src") or img.get("path_or_url") or ""
        alt = img.get("alt", "")
        
        # 将 Wikipedia 缩略图 URL 转换为原图 URL
        # 例如: .../thumb/5/5f/Image.png/250px-Image.png → .../5/5f/Image.png
        if "/thumb/" in img_url and "px-" in img_url:
            import re
            # 移除 /thumb/ 路径段和最后的 /XXXpx-filename 部分
            img_url = re.sub(r'/thumb/', '/', img_url)
            img_url = re.sub(r'/\d+px-[^/]+$', '', img_url)
            _LOGGER.info(f"Converted thumbnail to full-size: {img_url}")
        
        description = alt  # 默认使用 alt
        
        if vlm and img_url:
            try:
                # 速率限制：每张图片下载间隔 0.5 秒，避免 Wikipedia 429 错误
                import time
                if i > 0:
                    time.sleep(0.5)
                
                # 转换图片为 Base64
                # HumanMessage 已在文件顶部导入
                
                encoded_image = _encode_image(img_url)
                
                if encoded_image:
                    # 构造带图片的消息
                    vlm_message = HumanMessage(
                        content=[
                            {"type": "text", "text": "请用一句话简洁描述这张图片的内容，重点说明它展示了什么技术概念或架构。只输出描述，不要其他内容。"},
                            {"type": "image_url", "image_url": {"url": encoded_image}},
                        ]
                    )
                else:
                    raise ValueError(f"Failed to encode image: {img_url}")
                
                vlm_response = vlm.invoke([vlm_message])
                description = extract_text_content(vlm_response)[:100]  # 限制长度
                _LOGGER.info(f"VLM analyzed image {i+1}: {description[:50]}...")
            except Exception as e:
                _LOGGER.warning(f"VLM analysis failed for image {i+1}: {e}")
                description = "无法分析图片内容" # Don't just fallback to alt, keep distinct
        
        # Merge descriptions: VLM provides visual content
        # User request: Only use VLM description to avoid noise from bad captions
        combined_description = ""
        if description: 
             combined_description += f"{description}\n"
        
        if not combined_description:
            combined_description = "无描述信息"

        images_with_desc.append({
            "index": i,
            "element_id": img.get("element_id", f"img_{i}"),
            "url": img_url,
            "description": combined_description.strip()
        })
    
    # 准备图片信息供 LLM 匹配 - 使用唯一 element_id 而非顺序索引
    images_info = "\n".join([
        f"- 图片[{d['element_id']}]: {d['description']}"
        for d in images_with_desc
    ])
    
    # 构建 element_id -> image 的查找表
    images_by_id = {d["element_id"]: d for d in images_with_desc}
    available_images_by_id = {img.get("element_id", f"img_{i}"): img for i, img in enumerate(deduplicated_images)}
    
    # 3. 提取文章标题
    headings = re.findall(r'^(#{1,3}\s+.+)$', full_content, re.MULTILINE)
    if not headings:
        headings = ["无标题"]
    
    system_prompt = ILLUSTRATOR_MATCH_SYSTEM_PROMPT.format(
        images_info=images_info,
        headings_preview=chr(10).join(headings[:10])
    )

    user_prompt = ILLUSTRATOR_MATCH_USER_PROMPT.format(content_preview=full_content[:5000])

    try:
        # Illustrator 需要更大的上下文窗口来处理图片描述 + 文章内容
        llm = build_chat_llm(task_name="illustrator", num_ctx_override=16384)
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_prompt),
        ]
        response = llm.invoke(messages)
        content = extract_text_content(response)
        
        # 提取 JSON
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            json_str = json_match.group()
            # 修复常见的 JSON 转义错误 (如 LaTeX 公式中的反斜杠)
            # 将所有未跟随合法转义字符的反斜杠双写
            json_str = re.sub(r'\\([^"\\/bfnrtu])', r'\\\\\1', json_str)
            
            try:
                result = json.loads(json_str)
            except json.JSONDecodeError as je:
                _LOGGER.warning(f"JSON parse error: {je}. Trying to recover...")
                # 尝试更激进的修复：移除所有反斜杠 (除了转义引号的)
                json_str_fixed = re.sub(r'\\(?!")', '', json_str)
                try:
                    result = json.loads(json_str_fixed)
                except:
                    # 如果仍然失败，抛出原始错误
                    raise je
            placements = result.get("placements", [])
            
            # 构建最终 Markdown（插入图片）
            lines = full_content.split('\n')
            
            # 预处理：按行索引插入，需要处理偏移，或者倒序处理
            # 这里采用倒序插入，这样前面的索引不会受影响
            
            # 为了倒序处理，我们需要先计算出所有图片的插入行号
            insertion_ops = [] # (line_index, img_md)
            
            for p in placements:
                # 优先使用 image_id (element_id)，兼容旧版 image_index
                img_id = p.get("image_id") or p.get("element_id")
                img = None
                
                if img_id and img_id in available_images_by_id:
                    img = available_images_by_id[img_id]
                    _LOGGER.info(f"Image [{img_id}] found via ID lookup: {img}")
                else:
                    # Fallback: 旧版 image_index 兼容
                    img_idx = p.get("image_index", 0)
                    if isinstance(img_idx, int) and 0 <= img_idx < len(deduplicated_images):
                        img = deduplicated_images[img_idx]
                        img_id = img.get("element_id", f"img_{img_idx}")
                        _LOGGER.warning(f"Fallback to image_index {img_idx}: {img_id}")
                    else:
                        _LOGGER.warning(f"Image not found: id={img_id}, index={p.get('image_index')}")
                        continue
                
                if not img:
                    continue
                    
                # Log image object for debugging
                _LOGGER.info(f"Image [{img_id}] raw object: {img}")
                    
                # 优先检查 'src' (PDF assets) 和 'content' (URL images), 然后才是 'url'/'path_or_url'
                img_url = img.get("src") or img.get("content") or img.get("path_or_url") or img.get("url") or ""
                alt = img.get("alt", "")
                
                # 将 Wikipedia 缩略图 URL 转换为原图 URL
                if "/thumb/" in img_url and "px-" in img_url:
                    import re
                    img_url = re.sub(r'/thumb/', '/', img_url)
                    img_url = re.sub(r'/\d+px-[^/]+$', '', img_url)
                    _LOGGER.info(f"Image [{img_id}]: Converted to full-size URL: {img_url}")
                
                # 强制转换为相对路径 (Fix for host/web viewing)
                # 将 /data/workspace/artifacts/.../corpus/... 转换为 ../corpus/...
                if "/corpus/" in img_url and img_url.startswith("/"):
                    # Transform local container path to Web API path
                    # /data/workspace/artifacts/article_id/corpus/... -> /api/artifacts/article_id/corpus/...
                    # This enables the browser to load images via the rag-service static mount
                    if "/artifacts/" in img_url:
                            new_url = "/api/artifacts/" + img_url.split("/artifacts/")[1]
                    else:
                            # Fallback: try to construct using article_id
                            import re
                            new_url = re.sub(r'^.*/corpus/', f'/api/artifacts/{article_id}/corpus/', img_url)
                    
                    _LOGGER.info(f"Image [{img_id}]: Converted path '{img_url}' to Web URL '{new_url}'")
                    img_url = new_url
                
                caption = p.get("caption", "") or alt
                after_heading = p.get("after_heading", "")
                insert_after_text = p.get("insert_after_text", "").strip()
                
                if not img_url:
                    _LOGGER.warning(f"Image [{img_id}] has EMPTY URL! Skipping insertion or inserting placeholder. Source: {img}")
                else:
                    _LOGGER.info(f"Preparing to insert Image [{img_id}]: url='{img_url}' under heading '{after_heading}'")

                # 使用 HTML figure 格式，确保居中、合适尺寸和带说明文字
                img_md = f'''

<figure style="text-align: center; margin: 20px 0;">
  <img src="{img_url}" alt="{caption}" style="display: block; margin: 0 auto; width: 80%; max-width: 600px;">
  <figcaption style="margin-top: 8px; color: #666; font-size: 0.9em;">{caption}</figcaption>
</figure>
'''
                
                # 1. 找到 Heading 行
                heading_line_idx = -1
                for i, line in enumerate(lines):
                    # 宽松匹配：精确相等 OR以此结尾 OR 以此开头 (处理 LLM 只返回 "## 标题" 而忽略冒号后内容的情况)
                    clean_line = line.strip()
                    clean_target = after_heading.lstrip('#').strip()
                    if clean_line == after_heading or clean_line.endswith(clean_target) or (clean_target and clean_line.startswith(after_heading)):
                        heading_line_idx = i
                        break
                
                if heading_line_idx == -1:
                    _LOGGER.warning(f"Heading NOT found: '{after_heading}', skipping image [{img_id}]. Available headings: {[l for l in lines if l.strip().startswith('#')][:5]}...")
                    continue
                else:
                    _LOGGER.info(f"Heading found at line {heading_line_idx}: '{lines[heading_line_idx]}'")
                    
                # 2. 在 Heading 后查找插入点
                insert_line_idx = heading_line_idx + 1 # 默认插在标题后
                
                # 确定查找范围：直到下一个标题
                search_end_idx = len(lines)
                for i in range(heading_line_idx + 1, len(lines)):
                    if lines[i].strip().startswith("#"):
                        search_end_idx = i
                        break
                
                # 如果有具体文本锚点，尝试定位
                if insert_after_text:
                    import difflib
                    
                    found_anchor = False
                    best_score = 0.0
                    best_idx = -1
                    
                    # 归一化文本（移除空格和标点）
                    def normalize(s):
                        return "".join(c.lower() for c in s if c.isalnum())
                    
                    norm_target = normalize(insert_after_text)
                    
                    # 第一轮：尝试精确子串匹配（忽略大小写和标点）
                    if len(norm_target) > 5:
                        for i in range(heading_line_idx + 1, search_end_idx):
                            line_norm = normalize(lines[i])
                            # 如果锚点文本足够具体，且能在行中找到
                            if norm_target in line_norm:
                                insert_line_idx = i + 1
                                found_anchor = True
                                _LOGGER.info(f"Image [{img_id}]: Text match (Normalized substring) found at line {i+1}")
                                break
                    
                    # 第二轮：如果没找到，尝试模糊相似度匹配 (Levenshtein)
                    if not found_anchor and len(norm_target) > 10:
                        for i in range(heading_line_idx + 1, search_end_idx):
                            line_norm = normalize(lines[i])
                            if len(line_norm) < 5: continue
                            
                            # 计算相似度 ratio
                            matcher = difflib.SequenceMatcher(None, norm_target, line_norm)
                            ratio = matcher.ratio()
                            # 或者检查包含关系的相似度
                            if len(line_norm) > len(norm_target):
                                    # 如果行比目标长，检查是否包含目标（即寻找最佳子序列匹配）
                                    # 这里简化为直接比较 ratio，或者用 RealQuickRatio
                                    pass
                            
                            if ratio > best_score:
                                best_score = ratio
                                best_idx = i
                        
                        # 阈值判定 (0.7 比较宽松，因为 LLM 经常改写)
                        if best_score > 0.4: 
                            insert_line_idx = best_idx + 1
                            found_anchor = True
                            _LOGGER.info(f"Image [{img_id}]: Fuzzy match found at line {best_idx+1} (score={best_score:.2f})")
                    
                    if not found_anchor:
                        _LOGGER.info(f"Image [{img_id}]: Anchor text '{insert_after_text[:20]}...' not found (best score {best_score:.2f}) under {after_heading}, placing after heading")
                    
                    insertion_ops.append((insert_line_idx, img_md))

            # 执行插入 (倒序)
            insertion_ops.sort(key=lambda x: x[0], reverse=True)
            
            for line_idx, content in insertion_ops:
                lines.insert(line_idx, content)
            
            final_markdown = "\n".join(lines)
            
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
            # 保存到文件
            final_path = ""
            try:
                if article_id:
                    save_dir = get_drafts_dir(article_id)  # drafts 目录
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
            _LOGGER.warning(f"match_images_tool: no JSON found. Raw content:\n{content}")
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


@tool
def generate_illustration_plan_tool(article_id: str = "") -> Dict[str, Any]:
    """读取 corpus 中的 elements.jsonl，生成 illustration_plan.json。
    
    Args:
        article_id: 文章 ID
        
    Returns:
        illustration_plan 路径和统计信息
    """
    import glob
    from ...config.config import get_article_dir
    
    article_id = get_current_article_id(article_id)
    _LOGGER.info(f"generate_illustration_plan_tool: article_id={article_id}")
    
    if not article_id:
        return {"error": "Missing article_id"}
    
    # 1. 查找所有 elements.jsonl 文件
    article_dir = get_article_dir(article_id)
    elements_pattern = os.path.join(article_dir, "corpus", "*", "parsed", "elements.jsonl")
    elements_files = glob.glob(elements_pattern)
    
    _LOGGER.info(f"Found {len(elements_files)} elements.jsonl files")
    
    # 2. 读取所有图片/表格元素
    all_elements = []
    for ef in elements_files:
        doc_id = os.path.basename(os.path.dirname(os.path.dirname(ef)))
        try:
            with open(ef, "r", encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        elem = json.loads(line)
                        elem["doc_id"] = doc_id
                        all_elements.append(elem)
                    except:
                        pass
        except Exception as e:
            _LOGGER.warning(f"Error reading {ef}: {e}")
    
    _LOGGER.info(f"Loaded {len(all_elements)} elements from corpus")
    
    # 3. 筛选图片和表格元素
    image_elements = [e for e in all_elements if e.get("type") in ["image", "figure"]]
    table_elements = [e for e in all_elements if e.get("type") == "table"]
    
    # 4. 读取 draft 以确定插入位置 (简化：按章节标题匹配)
    drafts_dir = get_drafts_dir(article_id)
    draft_files = glob.glob(os.path.join(drafts_dir, "section_*.md"))
    
    headings = []
    for df in sorted(draft_files):
        try:
            with open(df, "r", encoding="utf-8") as f:
                content = f.read()
            # 提取标题
            import re
            for match in re.finditer(r'^(#{1,3})\s+(.+)$', content, re.MULTILINE):
                headings.append(match.group(2).strip())
        except:
            pass
    
    # 5. 生成 illustration_plan.json
    figures = []
    for idx, img in enumerate(image_elements[:10]):  # 最多 10 张图
        figure_id = f"fig_{idx + 1}"
        # 简单匹配：第 N 张图放在第 N 个标题后（如果存在）
        insert_after = headings[idx] if idx < len(headings) else headings[-1] if headings else ""
        
        figures.append({
            "figure_id": figure_id,
            "source": {
                "doc_id": img.get("doc_id", ""),
                "element_id": img.get("element_id", ""),
            },
            "src": img.get("src", ""), # Ensure src is passed to plan
            "caption": img.get("content", "")[:100] or f"图{idx + 1}",
            "insert_after_anchor": f"## {insert_after}" if insert_after else "",
            "layout": {"width": "70%", "align": "center"}
        })
    
    # 添加表格
    for idx, tbl in enumerate(table_elements[:5]):  # 最多 5 个表格
        figure_id = f"tbl_{idx + 1}"
        insert_after = headings[idx + len(image_elements)] if (idx + len(image_elements)) < len(headings) else ""
        
        figures.append({
            "figure_id": figure_id,
            "source": {
                "doc_id": tbl.get("doc_id", ""),
                "element_id": tbl.get("element_id", ""),
            },
            "type": "table",
            "caption": f"表{idx + 1}",
            "insert_after_anchor": f"## {insert_after}" if insert_after else "",
        })
    
    illustration_plan = {
        "article_id": article_id,
        "figures": figures,
        "stats": {
            "total_images": len(image_elements),
            "total_tables": len(table_elements),
            "planned_figures": len(figures)
        }
    }
    
    # 6. 保存 illustration_plan.json
    # 保存到 assets 目录
    assets_dir = os.path.join(article_dir, "assets")
    os.makedirs(assets_dir, exist_ok=True)
    
    plan_path = os.path.join(assets_dir, "illustration_plan.json")
    try:
        with open(plan_path, "w", encoding="utf-8") as f:
            json.dump(illustration_plan, f, ensure_ascii=False, indent=2)
        _LOGGER.info(f"Illustration plan saved to: {plan_path}")
    except Exception as e:
        _LOGGER.error(f"Failed to save illustration_plan: {e}")
        return {"error": str(e)}
    
    return {
        "illustration_plan_path": plan_path,
        "total_figures": len(figures),
        "image_elements": len(image_elements),
        "table_elements": len(table_elements),
    }
