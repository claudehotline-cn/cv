from __future__ import annotations

import re
import uuid
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .schema import OutlineOutput, OutlineSection


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
        return [
            f"| ![{alt}]({path}) |",
            "|:--:|",
            f"| 图 {figure_index}：{caption_text} |",
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
        # 使用“单列表格”实现居中 + 图注（避免 raw HTML 在部分前端被 sanitize）。
        return "\n".join(
            [
                f"| ![{alt}]({path}) |",
                "|:--:|",
                f"| 图 {figure_index}：{caption_text} |",
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
            break

        if not assigned:
            break

    return image_metadata


__all__ = [
    "dedupe_preserve_order",
    "ensure_article_id",
    "normalize_outline",
    "extract_markdown_headings",
    "insert_images_into_markdown",
    "collect_source_images",
    "build_fallback_image_metadata",
]
