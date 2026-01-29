from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..schemas import OutlineOutput, OutlineSection


_SECTION_ID_RE = re.compile(r"[^a-z0-9_]+")
_IMAGE_PLACEHOLDER_RE = re.compile(
    r"<!--\s*IMAGE\s*:\s*([a-zA-Z0-9_]+)\s*(?::\s*(\d+)\s*)?(?:\|\s*(.*?)\s*)?-->",
    re.DOTALL,
)


def dedupe_preserve_order(items: Iterable[str]) -> List[str]:
    seen: set[str] = set()
    out: List[str] = []
    for raw in items:
        item = (raw or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def ensure_article_id(article_id: Optional[str]) -> str:
    value = (article_id or "").strip()
    if value:
        return value
    return f"article-{uuid.uuid4().hex[:10]}"


def _sanitize_section_id(section_id: str, fallback: str) -> str:
    value = (section_id or "").strip().lower()
    value = value.replace("-", "_")
    value = _SECTION_ID_RE.sub("_", value).strip("_")
    if not value:
        return fallback
    if not value.startswith("sec_"):
        value = f"sec_{value}"
    return value


def normalize_outline(outline: OutlineOutput) -> Tuple[OutlineOutput, Dict[str, str]]:
    """归一化 Planner 输出的大纲：

    - section.id 去噪、统一前缀、保证唯一；
    - level 仅允许 2/3；
    - level=2 强制 parent_id=None；level=3 缺 parent_id 时回退为 level=2；
    - sections_to_research 过滤非法 id；
    - 返回 (normalized_outline, id_mapping_old_to_new)。
    """

    id_mapping: Dict[str, str] = {}
    used: set[str] = set()
    normalized_sections: List[OutlineSection] = []

    last_level2_id: Optional[str] = None

    for index, sec in enumerate(outline.sections or []):
        original_id = sec.id
        new_id = _sanitize_section_id(original_id, fallback=f"sec_{index+1}")

        if new_id in used:
            suffix = 2
            while f"{new_id}_{suffix}" in used:
                suffix += 1
            new_id = f"{new_id}_{suffix}"

        used.add(new_id)
        id_mapping[original_id] = new_id

        title = (sec.title or "").strip() or "未命名小节"
        level = sec.level if sec.level in (2, 3) else 2
        parent_id = (sec.parent_id or "").strip() or None
        is_core = bool(sec.is_core)

        if level == 2:
            parent_id = None
            last_level2_id = new_id
        else:
            parent_id = id_mapping.get(parent_id, parent_id)
            if not parent_id or parent_id not in used:
                # 没有合法父节点：降级为二级标题，避免出现孤儿三级标题。
                level = 2
                parent_id = None
                last_level2_id = new_id
            else:
                # 额外保护：若 parent_id 为空但上文存在二级标题，可就近挂靠。
                if not parent_id and last_level2_id:
                    parent_id = last_level2_id

        normalized_sections.append(
            OutlineSection(
                id=new_id,
                title=title,
                level=level,
                parent_id=parent_id,
                is_core=is_core,
            )
        )

    # 修正 sections_to_research：去重、过滤，并映射到新 id。
    allowed_ids = {sec.id for sec in normalized_sections}
    normalized_research_ids: List[str] = []
    for sec_id in outline.sections_to_research or []:
        mapped = id_mapping.get(sec_id, sec_id)
        mapped = (mapped or "").strip()
        if not mapped or mapped not in allowed_ids:
            continue
        if mapped in normalized_research_ids:
            continue
        normalized_research_ids.append(mapped)

    title = (outline.title or "").strip() or "未命名文章"
    normalized_outline = OutlineOutput(
        title=title,
        sections=normalized_sections,
        sections_to_research=normalized_research_ids,
    )
    return normalized_outline, id_mapping


def extract_markdown_headings(markdown: str) -> List[str]:
    """提取 Markdown 中所有标题行（# / ## / ### ...），用于结构一致性校验。"""

    headings: List[str] = []
    for line in (markdown or "").splitlines():
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            continue
        # 只保留形如 "# xxx" 的标题行；忽略 "#####" 但没有空格的情况。
        if re.match(r"^#{1,6}\s+", stripped):
            headings.append(stripped.rstrip())
    return headings


def normalize_heading_text(heading: str) -> str:
    """标准化标题：去掉 # 前缀和编号，只保留纯文字。
    
    例如：
    "## 1. 引言与背景" -> "引言与背景"
    "### 2.1 基本概念" -> "基本概念"
    """
    h = heading.strip()
    # 去掉开头的 # 符号和空格
    h = re.sub(r'^#{1,6}\s*', '', h)
    # 去掉开头的编号（如 "1." "2.1" "1.2.3" 等）
    h = re.sub(r'^\d+(\.\d+)*\.?\s*', '', h)
    return h.strip()


def compare_headings_lenient(draft_headings: List[str], refined_headings: List[str]) -> bool:
    """宽松的标题比较：只比较标题数量和纯文字内容，忽略编号差异。
    
    这允许 doc_refiner 在不改变标题结构的前提下微调文字。
    """
    if len(draft_headings) != len(refined_headings):
        return False
    
    for draft_h, refined_h in zip(draft_headings, refined_headings):
        # 提取标题级别（# 的数量）
        draft_level = len(re.match(r'^#+', draft_h).group()) if draft_h.startswith('#') else 0
        refined_level = len(re.match(r'^#+', refined_h).group()) if refined_h.startswith('#') else 0
        
        if draft_level != refined_level:
            return False
        
        # 比较纯文字内容
        draft_text = normalize_heading_text(draft_h)
        refined_text = normalize_heading_text(refined_h)
        
        if draft_text != refined_text:
            return False
    
    return True


def _upgrade_wikipedia_image_url(url: str) -> str:
    """将Wikipedia的缩略图URL转换为原图URL。
    
    示例：
    输入：.../250px-Transformer_architecture.png
    输出：.../Transformer_architecture.png
    """
    if "wikipedia.org" not in url.lower():
        return url
    
    # 匹配 /数字px-文件名 模式
    import re
    pattern = r'/(\d+)px-([^/]+)$'
    match = re.search(pattern, url)
    if match:
        # 移除尺寸前缀，保留原文件名
        filename = match.group(2)
        return re.sub(pattern, f'/{filename}', url)
    
    return url


def insert_images_into_markdown(
    markdown: str,
    outline: Dict[str, Any],
    image_metadata: Dict[str, List[Dict[str, Any]]],
    max_images_per_section: int = 2,
) -> str:
    """将 image_metadata 中的图片按 section 插入到对应章节末尾（纯规则，不用 LLM）。"""

    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list) or not sections:
        return markdown

    lines = (markdown or "").splitlines()
    figure_index = 0

    def _render_figure(path: str, alt: str, caption: str) -> List[str]:
        nonlocal figure_index
        figure_index += 1
        caption_text = str(caption).strip() or str(alt).strip() or "插图"
        # 将 Wikipedia 缩略图转换为原图
        path = _upgrade_wikipedia_image_url(path)
        return [
            '<div align="center">',
            f'  <img src="{path}" alt="{alt}"/>',
            f'  <p><em>图 {figure_index}：{caption_text}</em></p>',
            '</div>',
        ]

    # 1) 先定位每个 outline section 的标题行位置（按 outline 顺序向前搜索，避免同名误匹配）。
    positions: List[Dict[str, Any]] = []
    search_start = 0
    for sec in sections:
        if not isinstance(sec, dict):
            positions.append({"id": None, "level": None, "title": None, "start": None})
            continue
        section_id = str(sec.get("id") or "")
        title = str(sec.get("title") or "").strip()
        level = int(sec.get("level") or 2)
        expected = f"{'#' * level} {title}".strip()

        found: Optional[int] = None
        if title:
            for idx in range(search_start, len(lines)):
                if lines[idx].lstrip().rstrip() == expected:
                    found = idx
                    search_start = idx + 1
                    break

        positions.append({"id": section_id, "level": level, "title": title, "start": found})

    # 2) 计算每个 section 的插入位置：找下一个 outline section，其 level <= 当前 level。
    insert_ops: List[Tuple[int, List[str]]] = []
    for i, pos in enumerate(positions):
        start_idx = pos.get("start")
        if not isinstance(start_idx, int):
            continue

        section_id = pos.get("id") or ""
        current_level = int(pos.get("level") or 2)
        if not section_id:
            continue

        end_idx = len(lines)
        for j in range(i + 1, len(positions)):
            next_start = positions[j].get("start")
            next_level = positions[j].get("level")
            if not isinstance(next_start, int):
                continue
            if int(next_level or 2) <= current_level:
                end_idx = next_start
                break

        candidates = image_metadata.get(section_id) or []
        if not isinstance(candidates, list) or not candidates:
            continue

        image_lines: List[str] = []
        section_slice = "\n".join(lines[start_idx:end_idx])
        for item in candidates[: max_images_per_section or 0]:
            if not isinstance(item, dict):
                continue
            path = item.get("path_or_url") or item.get("url") or item.get("path")
            path = (str(path) if path is not None else "").strip()
            if not path:
                continue
            if path in section_slice:
                continue
            alt = (item.get("alt") or item.get("caption_hint") or "插图")
            alt = str(alt).strip() or "插图"
            caption = (item.get("caption_hint") or item.get("alt") or alt)
            caption = str(caption).strip() or alt
            image_lines.extend(_render_figure(path=path, alt=alt, caption=caption))
            image_lines.append("")

        if not image_lines:
            continue

        insertion: List[str] = []
        if end_idx > 0 and lines[end_idx - 1].strip():
            insertion.append("")
        insertion.extend(image_lines)
        insertion.append("")
        insert_ops.append((end_idx, insertion))

    # 3) 从后往前执行插入，避免位置偏移。
    for end_idx, insertion in sorted(insert_ops, key=lambda x: x[0], reverse=True):
        lines = lines[:end_idx] + insertion + lines[end_idx:]

    return "\n".join(lines).strip()


def replace_image_placeholders(
    markdown: str,
    image_metadata: Dict[str, List[Dict[str, Any]]],
    *,
    max_images_per_section: int = 2,
) -> str:
    """用 image_metadata 替换 Writer 输出的插图占位符。

    支持两种格式：
    - `<!--IMAGE:sec_x-->`：在该位置插入本节最多 max_images_per_section 张图。
    - `<!--IMAGE:sec_x:1-->` / `<!--IMAGE:sec_x:2-->`：在该位置仅插入第 n 张图（1-based）。

    若找不到对应图片或 section_id 非法，则移除占位符，不保留注释。
    """

    if not markdown:
        return markdown
    if not isinstance(image_metadata, dict) or not image_metadata:
        # 没有可插入的图片：移除所有占位符，避免用户看到注释。
        return _IMAGE_PLACEHOLDER_RE.sub("", markdown).strip()

    used_paths_by_section: Dict[str, set[str]] = {}
    used_count_by_section: Dict[str, int] = {}
    figure_index = 0

    def _render_figure(path: str, alt: str, caption: str) -> str:
        nonlocal figure_index
        figure_index += 1
        caption_text = str(caption).strip() or str(alt).strip() or "插图"
        # 将 Wikipedia 缩略图转换为原图，保留原始尺寸
        path = _upgrade_wikipedia_image_url(path)
        return "\n".join(
            [
                '<div align="center">',
                f'  <img src="{path}" alt="{alt}"/>',
                f'  <p><em>图 {figure_index}：{caption_text}</em></p>',
                '</div>',
            ]
        )

    def _render_image(item: Dict[str, Any], caption_override: str = "") -> str:
        path = item.get("path_or_url") or item.get("url") or item.get("path")
        path = (str(path) if path is not None else "").strip()
        if not path:
            return ""
        alt = (item.get("alt") or item.get("caption_hint") or "插图")
        alt = str(alt).strip() or "插图"

        caption = (caption_override or item.get("caption_hint") or item.get("alt") or alt)
        caption = str(caption).strip() or alt
        return _render_figure(path=path, alt=alt, caption=caption)

    def _replacement(match: re.Match[str]) -> str:
        section_id = (match.group(1) or "").strip()
        index_raw = (match.group(2) or "").strip()
        caption_override = (match.group(3) or "").strip()
        candidates = image_metadata.get(section_id) or []
        if not isinstance(candidates, list) or not candidates:
            return ""

        used_paths = used_paths_by_section.setdefault(section_id, set())
        used_count = used_count_by_section.get(section_id, 0)

        def _insert_one(idx0: int) -> str:
            if idx0 < 0 or idx0 >= len(candidates):
                return ""
            item = candidates[idx0]
            if not isinstance(item, dict):
                return ""
            path = item.get("path_or_url") or item.get("url") or item.get("path")
            path = (str(path) if path is not None else "").strip()
            if not path or path in used_paths:
                return ""
            rendered = _render_image(item, caption_override=caption_override if index_raw else "")
            if not rendered:
                return ""
            used_paths.add(path)
            used_count_by_section[section_id] = used_count_by_section.get(section_id, 0) + 1
            return rendered

        # 指定索引：只插入一张
        if index_raw:
            try:
                idx = int(index_raw)
            except ValueError:
                return ""
            if idx <= 0:
                return ""
            if max_images_per_section and used_count >= max_images_per_section:
                return ""
            return _insert_one(idx - 1)

        # 未指定索引：插入本节剩余可用图片（最多 max_images_per_section）
        if max_images_per_section and used_count >= max_images_per_section:
            return ""
        remaining = (max_images_per_section - used_count) if max_images_per_section else len(candidates)
        if remaining <= 0:
            return ""

        lines: List[str] = []
        for i in range(len(candidates)):
            if remaining <= 0:
                break
            rendered = _insert_one(i)
            if not rendered:
                continue
            lines.append(rendered)
            remaining -= 1

        return "\n".join(lines)

    replaced = _IMAGE_PLACEHOLDER_RE.sub(_replacement, markdown)
    # 清理遗留占位符（例如无图、非法索引等情况），避免注释残留。
    replaced = _IMAGE_PLACEHOLDER_RE.sub("", replaced)
    # 规范化多余空行（保持轻量，不做复杂格式化）
    replaced = re.sub(r"\n{3,}", "\n\n", replaced)
    return replaced.strip()


def collect_source_images(sources: Dict[str, Any]) -> List[Dict[str, Any]]:
    """从 sources 中提取去重后的图片列表（仅原始图片，不做生成）。"""

    images: List[Dict[str, Any]] = []
    seen: set[str] = set()

    if not isinstance(sources, dict):
        return images

    for source_id, src in sources.items():
        if not isinstance(src, dict):
            continue
        for img in (src.get("images") or []):
            if not isinstance(img, dict):
                continue
            path = img.get("path_or_url") or img.get("url") or img.get("src") or img.get("path")
            path = (str(path) if path is not None else "").strip()
            if not path or path in seen:
                continue
            seen.add(path)
            images.append(
                {
                    "source_id": str(source_id),
                    "path_or_url": path,
                    "caption_hint": (str(img.get("caption_hint") or img.get("alt") or "")).strip(),
                }
            )

    return images


def build_fallback_image_metadata(
    outline: Dict[str, Any],
    source_images: List[Dict[str, Any]],
    prefer_section_ids: Optional[List[str]] = None,
    *,
    max_images_per_section: int = 2,
) -> Dict[str, List[Dict[str, Any]]]:
    """当 LLM 未输出 image_metadata 时，使用纯规则将来源图片分配到章节中。"""

    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list) or not sections:
        return {}

    section_ids: List[str] = []
    core_ids: List[str] = []
    for sec in sections:
        if not isinstance(sec, dict) or not sec.get("id"):
            continue
        sec_id = str(sec["id"])
        section_ids.append(sec_id)
        if bool(sec.get("is_core")):
            core_ids.append(sec_id)

    if not section_ids or not isinstance(source_images, list) or not source_images:
        return {}

    prefer: List[str] = []
    if prefer_section_ids:
        allowed = set(section_ids)
        for sec_id in prefer_section_ids:
            if sec_id in allowed and sec_id not in prefer:
                prefer.append(sec_id)

    target_ids = prefer or core_ids or section_ids[:1]
    if not target_ids:
        target_ids = section_ids[:1]

    per_section_limit = max(0, int(max_images_per_section))
    if per_section_limit <= 0:
        return {sec_id: [] for sec_id in section_ids}

    image_metadata: Dict[str, List[Dict[str, Any]]] = {sec_id: [] for sec_id in section_ids}

    # round-robin 分配，优先填满 target_ids；如果图片多再继续循环 target_ids
    idx = 0
    for img in source_images:
        if not isinstance(img, dict):
            continue
        source_id = (str(img.get("source_id") or "")).strip()
        path = (str(img.get("path_or_url") or "")).strip()
        if not source_id or not path:
            continue

        # 找到一个还有容量的 section
        assigned = False
        for _ in range(len(target_ids)):
            sec_id = target_ids[idx % len(target_ids)]
            idx += 1
            if len(image_metadata.get(sec_id, [])) >= per_section_limit:
                continue
            image_metadata[sec_id].append(
                {
                    "source_id": source_id,
                    "path_or_url": path,
                    "caption_hint": (str(img.get("caption_hint") or "")).strip(),
                }
            )
            assigned = True
    return image_metadata


def filter_unwanted_sections(markdown: str) -> str:
    """移除技术标记类section和遗留的占位符。
    
    功能：
    1. 移除包含不良关键词的section（如"插图占位符"）
    2. 移除所有 <!--IMAGE:...--> 占位符行
    """
    import re
    
    # 1. 先移除所有IMAGE占位符行
    markdown = re.sub(r'\n*<!--IMAGE:[^>]*-->\n*', '\n\n', markdown)
    
    # 需要移除的section标题关键词
    unwanted_keywords = [
        "插图占位符", "图片占位符", "占位符",
        "代码示例", "示例代码",
        "格式说明", "使用说明",
        "技术说明", "实现细节",
    ]
    
    lines = markdown.split('\n')
    filtered_lines = []
    skip_until_next_section = False
    
    for line in lines:
        # 检查是否是标题行
        heading_match = re.match(r'^(#{2,3})\s+(.+)$', line)
        
        if heading_match:
            heading_text = heading_match.group(2).strip()
            # 移除可能的编号（如"2.10 "）
            heading_text_clean = re.sub(r'^\d+(\.\d+)*\s+', '', heading_text)
            
            # 检查是否包含不良关键词
            is_unwanted = any(kw in heading_text_clean for kw in unwanted_keywords)
            
            if is_unwanted:
                # 跳过这个section，直到遇到下一个同级或更高级标题
                skip_until_next_section = True
                continue
            else:
                # 这是正常的标题，停止跳过
                skip_until_next_section = False
                filtered_lines.append(line)
        elif skip_until_next_section:
            # 跳过这个section的内容
            continue
        else:
            # 正常内容，保留
            filtered_lines.append(line)
    
    return '\n'.join(filtered_lines)


def fix_latex_commands(markdown: str) -> str:
    """修复常见的LaTeX命令损坏问题。
    
    问题原因：JSON序列化或LLM输出时反斜杠可能丢失。
    例如：\\frac 变成 rac, \\sqrt 变成 qrt
    """
    if not markdown:
        return markdown
    
    import re
    
    # 常见的LaTeX命令前缀修复映射
    latex_fixes = [
        # 分数和根号
        (r'(?<![\\a-zA-Z])frac\{', r'\\frac{'),
        (r'(?<![\\a-zA-Z])sqrt\{', r'\\sqrt{'),
        (r'(?<![\\a-zA-Z])sqrt\[', r'\\sqrt['),
        # 希腊字母
        (r'(?<![\\a-zA-Z])alpha(?![a-zA-Z])', r'\\alpha'),
        (r'(?<![\\a-zA-Z])beta(?![a-zA-Z])', r'\\beta'),
        (r'(?<![\\a-zA-Z])gamma(?![a-zA-Z])', r'\\gamma'),
        (r'(?<![\\a-zA-Z])delta(?![a-zA-Z])', r'\\delta'),
        (r'(?<![\\a-zA-Z])epsilon(?![a-zA-Z])', r'\\epsilon'),
        (r'(?<![\\a-zA-Z])theta(?![a-zA-Z])', r'\\theta'),
        (r'(?<![\\a-zA-Z])lambda(?![a-zA-Z])', r'\\lambda'),
        (r'(?<![\\a-zA-Z])sigma(?![a-zA-Z])', r'\\sigma'),
        (r'(?<![\\a-zA-Z])omega(?![a-zA-Z])', r'\\omega'),
        # 数学函数
        (r'(?<![\\a-zA-Z])sum(?![a-zA-Z])', r'\\sum'),
        (r'(?<![\\a-zA-Z])prod(?![a-zA-Z])', r'\\prod'),
        (r'(?<![\\a-zA-Z])int(?![a-zA-Z])', r'\\int'),
        (r'(?<![\\a-zA-Z])exp(?![a-zA-Z\(])', r'\\exp'),
        (r'(?<![\\a-zA-Z])log(?![a-zA-Z\(])', r'\\log'),
        (r'(?<![\\a-zA-Z])sin(?![a-zA-Z\(])', r'\\sin'),
        (r'(?<![\\a-zA-Z])cos(?![a-zA-Z\(])', r'\\cos'),
        (r'(?<![\\a-zA-Z])tan(?![a-zA-Z\(])', r'\\tan'),
        # 文本格式
        (r'(?<![\\a-zA-Z])text\{', r'\\text{'),
        (r'(?<![\\a-zA-Z])textbf\{', r'\\textbf{'),
        (r'(?<![\\a-zA-Z])mathbf\{', r'\\mathbf{'),
        (r'(?<![\\a-zA-Z])mathrm\{', r'\\mathrm{'),
        # 其他常用
        (r'(?<![\\a-zA-Z])cdot(?![a-zA-Z])', r'\\cdot'),
        (r'(?<![\\a-zA-Z])times(?![a-zA-Z])', r'\\times'),
        (r'(?<![\\a-zA-Z])left(?![a-zA-Z])', r'\\left'),
        (r'(?<![\\a-zA-Z])right(?![a-zA-Z])', r'\\right'),
        (r'(?<![\\a-zA-Z])begin\{', r'\\begin{'),
        (r'(?<![\\a-zA-Z])end\{', r'\\end{'),
        # rac -> \frac (特殊情况：反斜杠完全丢失)
        (r'\brac\{', r'\\frac{'),
        (r'\bqrt\{', r'\\sqrt{'),
        # \text{sqrt} -> \sqrt (LLM错误)
        (r'\\text\{sqrt\}', r'\\sqrt'),
        (r'\\text\{frac\}', r'\\frac'),
    ]
    
    result = markdown
    for pattern, replacement in latex_fixes:
        result = re.sub(pattern, replacement, result)
    
    return result


def add_heading_numbers(markdown: str) -> str:
    """为 Markdown 标题自动添加层级编号。

    示例：
    ## Introduction → ## 1. Introduction
    ### Background → ### 1.1 Background
    ### Motivation → ### 1.2 Motivation
    ## Methods → ## 2. Methods
    """
    if not markdown:
        return markdown

    lines = markdown.splitlines()
    h2_counter = 0
    h3_counter = 0
    result_lines: List[str] = []

    for line in lines:
        stripped = line.lstrip()
        
        # 检测二级标题 ##
        if stripped.startswith("## ") and not stripped.startswith("### "):
            h2_counter += 1
            h3_counter = 0  # 重置三级计数
            title = stripped[3:].strip()
            # 跳过已有编号的标题
            if re.match(r"^\d+\.?\s", title):
                result_lines.append(line)
            else:
                indent = line[:len(line) - len(stripped)]
                result_lines.append(f"{indent}## {h2_counter}. {title}")
        
        # 检测三级标题 ###
        elif stripped.startswith("### "):
            h3_counter += 1
            title = stripped[4:].strip()
            # 跳过已有编号的标题
            if re.match(r"^\d+\.\d+\.?\s", title):
                result_lines.append(line)
            else:
                indent = line[:len(line) - len(stripped)]
                result_lines.append(f"{indent}### {h2_counter}.{h3_counter} {title}")
        
        else:
            result_lines.append(line)

    return "\n".join(result_lines)


__all__ = [
    "dedupe_preserve_order",
    "ensure_article_id",
    "normalize_outline",
    "extract_markdown_headings",
    "normalize_heading_text",
    "compare_headings_lenient",
    "insert_images_into_markdown",
    "filter_unwanted_sections",
    "fix_latex_commands",
    "add_heading_numbers",
    "collect_source_images",
    "build_fallback_image_metadata",
]
