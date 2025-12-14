from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schema import OutlineOutput, OutlineSection


_SECTION_ID_RE = re.compile(r"[^a-z0-9_]+")


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
            alt = (item.get("caption_hint") or item.get("alt") or "插图")
            alt = str(alt).strip() or "插图"
            image_lines.append(f"![{alt}]({path})")

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


__all__ = [
    "dedupe_preserve_order",
    "ensure_article_id",
    "normalize_outline",
    "extract_markdown_headings",
    "insert_images_into_markdown",
]
