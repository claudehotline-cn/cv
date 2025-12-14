from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_runtime import build_chat_llm, build_structured_chat_llm, invoke_llm_with_timeout
from .prompts import COMMON_CONSTRAINTS_ZH
from .schema import ImageSelectionOutput, OutlineOutput, ResearcherOutput, SectionDraftOutput
from .tools_files import export_markdown, fetch_url_with_images, load_text_from_file
from .workflow_utils import extract_markdown_headings, insert_images_into_markdown, normalize_outline, replace_image_placeholders

_LOGGER = logging.getLogger("article_agent.sub_agents")


def _strip_markdown_fence(text: str) -> str:
    """去掉围绕全文的 ``` 代码块包裹（如 ```markdown ... ```）。"""

    if not isinstance(text, str):
        return text

    stripped = text.strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        inner = "\n".join(lines[1:-1])
        return inner.strip("\n")
    return text


def _strip_reasoning_block(text: str) -> str:
    """去掉模型输出中的显式推理块（如 <think>...</think>）。"""

    if not isinstance(text, str):
        return text

    cleaned = re.sub(r"<think[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def collector_agent(
    urls: List[str],
    file_paths: List[str],
    *,
    max_text_chars: int = 60000,
    max_overview_chars: int = 4000,
    max_images_per_source: int = 30,
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Collector：拉取来源文本与图片，并生成轻量概览供 Planner 使用。"""

    sources: Dict[str, Any] = {}
    overview: Dict[str, Any] = {}

    for idx, url in enumerate(urls or []):
        source_id = f"url_{idx}"
        try:
            data = fetch_url_with_images(url, max_images=max_images_per_source, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            images = data.get("images") or []
            sources[source_id] = {
                "source_id": source_id,
                "kind": "url",
                "url": url,
                "title": data.get("title", ""),
                "text": text,
                "images": [
                    {
                        "path_or_url": (img.get("url") or img.get("src") or ""),
                        "alt": (img.get("alt") or ""),
                    }
                    for img in images
                    if isinstance(img, dict) and (img.get("url") or img.get("src"))
                ],
            }
            overview[source_id] = {
                "source_id": source_id,
                "kind": "url",
                "url": url,
                "title": data.get("title", ""),
                "rough_snippet": snippet,
                "num_images": len(images) if isinstance(images, list) else 0,
            }
        except Exception as exc:  # pragma: no cover - 防御性
            _LOGGER.warning("collector.fetch_url_failed url=%s error=%s", url, exc)
            overview[source_id] = {
                "source_id": source_id,
                "kind": "url",
                "url": url,
                "title": "",
                "rough_snippet": "",
                "num_images": 0,
                "error": str(exc),
            }

    for idx, path in enumerate(file_paths or []):
        source_id = f"file_{idx}"
        try:
            data = load_text_from_file(path, max_text_chars=max_text_chars)
            text = data.get("text") or ""
            snippet = text[:max_overview_chars] if isinstance(text, str) else ""
            sources[source_id] = {
                "source_id": source_id,
                "kind": "file",
                "path": data.get("path", path),
                "title": data.get("path", path),
                "text": text,
                "images": [],
            }
            overview[source_id] = {
                "source_id": source_id,
                "kind": "file",
                "path": data.get("path", path),
                "title": data.get("path", path),
                "rough_snippet": snippet,
                "num_images": 0,
            }
        except Exception as exc:  # pragma: no cover - 防御性
            _LOGGER.warning("collector.load_file_failed path=%s error=%s", path, exc)
            overview[source_id] = {
                "source_id": source_id,
                "kind": "file",
                "path": path,
                "title": path,
                "rough_snippet": "",
                "num_images": 0,
                "error": str(exc),
            }

    return sources, overview


def planner_agent(instruction: str, rough_sources_overview: Any) -> OutlineOutput:
    system_prompt = f"""
你是 Planner 子 Agent，负责为一篇技术文章设计大纲。

【输入】
- instruction：用户对文章的整体要求（主题、读者、语气、篇幅、重点等）。
- rough_sources_overview：信息来源的概览列表或字典，每个来源包含 source_id、类型（网页/文件）、简要内容概览等。

【任务目标】
1. 基于 instruction 和 rough_sources_overview，为文章设计结构清晰、层级明确的大纲。
2. 输出文章总标题 title。
3. 输出 sections 列表，每个 section 至少包含：
   - id：小写字母 + 下划线组成的唯一字符串，如 "sec_intro"。
   - title：该节标题。
   - level：数字 2 或 3，表示 Markdown 的 ## 或 ### 级别。
   - parent_id：可选。若为三级标题，指向所属二级标题的 id。
   - is_core：布尔值，是否为核心内容部分。
4. 输出 sections_to_research：需要 Researcher 重点研究的 section_id 列表（只列 id）。

【输出格式】
你必须输出一个 JSON：
{{
  "title": "文章标题",
  "sections": [
    {{"id": "sec_intro", "title": "背景与目标", "level": 2, "parent_id": null, "is_core": false}}
  ],
  "sections_to_research": ["sec_intro"]
}}

【约束】
- 所有 section.id 必须全局唯一。
- sections_to_research 中的所有 id 必须来自 sections 列表中的 id。
- 大纲应兼顾“背景/问题 → 架构/流程 → 关键实现 → 实践建议/案例 → 总结展望”的结构。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    prompt_obj = {"instruction": instruction, "rough_sources_overview": rough_sources_overview}
    prompt = json.dumps(prompt_obj, ensure_ascii=False)

    structured_llm = build_structured_chat_llm(OutlineOutput, task_name="planner")

    def _call():
        return structured_llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )

    result = invoke_llm_with_timeout(task_name="planner", fn=_call, timeout_sec=90.0)
    outline = result if isinstance(result, OutlineOutput) else OutlineOutput.model_validate(result)
    normalized, _id_mapping = normalize_outline(outline)
    return normalized


def researcher_agent(
    outline: Dict[str, Any],
    sections_to_research: List[str],
    sources: Dict[str, Any],
    *,
    target_section_ids: Optional[List[str]] = None,
    timeout_sec: float = 240.0,
) -> Tuple[ResearcherOutput, List[str]]:
    """Researcher：按大纲整理资料，输出 section_notes/image_metadata/source_summaries。

    返回 (output, extra_section_note_keys)，其中 extra_section_note_keys 是被过滤的非法 section_id。
    """

    outline_sections = outline.get("sections") if isinstance(outline, dict) else None
    allowed_section_ids: List[str] = []
    if isinstance(outline_sections, list):
        for item in outline_sections:
            if isinstance(item, dict) and item.get("id"):
                allowed_section_ids.append(str(item["id"]))
    allowed_section_ids = [sec_id for sec_id in allowed_section_ids if sec_id]

    if target_section_ids:
        required_ids = [sec_id for sec_id in target_section_ids if sec_id in allowed_section_ids]
    else:
        required_ids = allowed_section_ids

    sources = sources if isinstance(sources, dict) else {}
    allowed_source_ids = [str(k) for k in sources.keys()]

    # 仅将必要字段送入 LLM，并对 text 做截断，避免 prompt 失控。
    MAX_SOURCE_TEXT_CHARS = 15000
    prompt_sources: Dict[str, Any] = {}
    allowed_image_paths: set[str] = set()
    for source_id, src in sources.items():
        if not isinstance(src, dict):
            continue
        text = src.get("text") or ""
        if isinstance(text, str) and len(text) > MAX_SOURCE_TEXT_CHARS:
            text = text[:MAX_SOURCE_TEXT_CHARS]

        images_out: List[Dict[str, Any]] = []
        for img in (src.get("images") or []):
            if not isinstance(img, dict):
                continue
            path = img.get("path_or_url") or img.get("url") or img.get("src")
            path = (str(path) if path is not None else "").strip()
            if not path:
                continue
            allowed_image_paths.add(path)
            images_out.append(
                {
                    "path_or_url": path,
                    "alt": (img.get("alt") or ""),
                }
            )

        prompt_sources[str(source_id)] = {
            "source_id": str(source_id),
            "kind": src.get("kind"),
            "url": src.get("url"),
            "path": src.get("path"),
            "title": src.get("title"),
            "text": text,
            "images": images_out,
        }

    required_clause = (
        f"- 你本次只需要为这些 section_id 输出笔记与图片元数据：{required_ids}。"
        if target_section_ids
        else "- 你必须为大纲中的每一个 section_id 都输出 section_notes（即便只有 NO_DATA 占位）。"
    )

    system_prompt = f"""
你是 Researcher 子 Agent，负责根据大纲和资料，为每个小节整理“原文素材池”。

【输入】
- outline：文章大纲（title + sections 列表），这是本次写作的权威结构。
- sections_to_research：需要重点研究的 section_id 列表。
- sources：按 source_id 分组的原始资料，每个来源包含 text 和可选的 images 元数据。

【任务目标】
1. 按照 outline 中的 section_id，将 sources 中的有效信息拆分、归类、重组到对应小节的笔记中。
2. 对 sections_to_research 中的节，给出更详细、更全面的笔记。
3. 输出是给 Writer 用的“素材池”，不是短摘要：尽量保留技术细节与关键点，结构清晰即可。

【输出结构】
你必须输出一个 JSON：
{{
  "section_notes": {{
    "<section_id>": "<该节素材笔记，基于资料重写，允许条目/分段>",
    ...
  }},
  "image_metadata": {{
    "<section_id>": [
      {{"source_id": "src_1", "path_or_url": "原图路径或URL", "caption_hint": "图片内容提示"}}
    ]
  }},
  "source_summaries": {{
    "<source_id>": "该来源的 1-3 段总结"
  }}
}}

【section_id 约束（非常重要）】
1. 你只能使用系统提供的大纲中的 section_id 作为键，不得自创 id。
2. {required_clause}
3. 若某节在资料中几乎找不到信息，也必须输出该 key，值写为：
   "NO_DATA: 本节在当前资料中未找到足够信息。"
4. 严禁使用 "main"、"other"、"misc"、"summary" 等不在大纲里的键名。

【图片约束（非常重要）】
- image_metadata 中的 path_or_url 必须来自 sources.images，绝不能伪造或生成新的 URL。

【禁止事项】
- 禁止输出 JSON 以外的任何文字。
- 禁止在没有依据的情况下编造具体事实、数据或引用。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    # 仅传入“有效的重点节”，减少模型被无效 id 干扰。
    allowed_section_id_set = set(allowed_section_ids)
    filtered_sections_to_research = [
        sec_id for sec_id in (sections_to_research or []) if sec_id in allowed_section_id_set
    ]

    prompt_obj = {
        "outline": outline,
        "sections_to_research": filtered_sections_to_research,
        "required_section_ids": required_ids,
        "sources": prompt_sources,
    }
    prompt = json.dumps(prompt_obj, ensure_ascii=False)

    structured_llm = build_structured_chat_llm(ResearcherOutput, task_name="researcher")

    def _call():
        return structured_llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )

    result = invoke_llm_with_timeout(task_name="researcher", fn=_call, timeout_sec=timeout_sec)
    output = result if isinstance(result, ResearcherOutput) else ResearcherOutput.model_validate(result)

    extra_keys: List[str] = []

    # section_notes：过滤非法 key，并补齐必需 section_id
    raw_notes = output.section_notes if isinstance(output.section_notes, dict) else {}
    cleaned_notes: Dict[str, str] = {}
    for key, value in raw_notes.items():
        sec_id = str(key)
        if sec_id not in allowed_section_ids:
            extra_keys.append(sec_id)
            continue
        if isinstance(value, str) and value.strip():
            cleaned_notes[sec_id] = value.strip()

    for sec_id in required_ids:
        if not cleaned_notes.get(sec_id):
            cleaned_notes[sec_id] = "NO_DATA: 本节在当前资料中未找到足够信息。"

    # image_metadata：按节过滤，并只保留 sources 中已有的原图
    raw_images = output.image_metadata if isinstance(output.image_metadata, dict) else {}
    cleaned_images: Dict[str, List[Dict[str, Any]]] = {}
    for key, items in raw_images.items():
        sec_id = str(key)
        if sec_id not in allowed_section_ids:
            continue
        if not isinstance(items, list):
            continue
        kept: List[Dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            source_id = (str(item.get("source_id") or "")).strip()
            path = item.get("path_or_url") or item.get("url") or item.get("path")
            path = (str(path) if path is not None else "").strip()
            if not source_id or source_id not in allowed_source_ids:
                continue
            if not path or path not in allowed_image_paths:
                continue
            kept.append(
                {
                    "source_id": source_id,
                    "path_or_url": path,
                    "caption_hint": (str(item.get("caption_hint") or item.get("alt") or "")).strip(),
                }
            )
        cleaned_images[sec_id] = kept

    for sec_id in required_ids:
        cleaned_images.setdefault(sec_id, [])

    # 若 sources 中存在图片但 LLM 没选出任何可用图片，则追加一次“只选图”的 LLM 调用补齐 image_metadata。
    total_images = sum(len(v) for v in cleaned_images.values() if isinstance(v, list))
    if total_images == 0 and allowed_image_paths and allowed_section_ids:
        image_system_prompt = f"""
你是 Illustrator 子 Agent，负责为文章各个小节挑选合适的“原始图片”并输出 image_metadata。

【输入】
- outline：文章大纲（包含 sections）。
- sections_to_research：重点节列表（可用于优先分配图片）。
- sources：每个来源的候选图片列表（images）。

【任务】
- 仅从 sources.images 中挑选图片，绝不生成新图片或伪造 URL。
- 尽量选择与内容相关、可作为说明的图片。
- 当候选图片数量 >= 2 时，你必须在全篇累计至少选出 2 张图片（分配到一个或多个 section 均可）。
- 每个 section 最多选择 2 张图片。

【输出】
你必须输出一个 JSON：
{{
  "image_metadata": {{
    "<section_id>": [
      {{"source_id": "src_1", "path_or_url": "原图URL", "caption_hint": "简短说明"}}
    ],
    ...
  }}
}}

【约束】
- section_id 只能来自 outline.sections[*].id。
- path_or_url 必须严格等于系统提供的某个 sources.images[*].path_or_url（不要改写、不要补全、不要缩写）。

{COMMON_CONSTRAINTS_ZH}
""".strip()

        image_prompt_obj = {
            "outline": outline,
            "sections_to_research": filtered_sections_to_research,
            "required_section_ids": required_ids,
            "sources_images": {
                src_id: (src.get("images") if isinstance(src, dict) else [])
                for src_id, src in prompt_sources.items()
            },
        }
        image_prompt = json.dumps(image_prompt_obj, ensure_ascii=False)
        image_llm = build_structured_chat_llm(ImageSelectionOutput, task_name="researcher_select_images")

        def _call_images():
            return image_llm.invoke(
                [
                    SystemMessage(content=image_system_prompt),
                    HumanMessage(content=image_prompt),
                ]
            )

        try:
            img_result = invoke_llm_with_timeout(
                task_name="researcher_select_images",
                fn=_call_images,
                timeout_sec=120.0,
            )
            img_output = img_result if isinstance(img_result, ImageSelectionOutput) else ImageSelectionOutput.model_validate(img_result)
            raw_images2 = img_output.image_metadata if isinstance(img_output.image_metadata, dict) else {}
            cleaned_images2: Dict[str, List[Dict[str, Any]]] = {sec_id: [] for sec_id in required_ids}
            for key, items in raw_images2.items():
                sec_id = str(key)
                if sec_id not in allowed_section_ids:
                    continue
                if not isinstance(items, list):
                    continue
                kept: List[Dict[str, Any]] = []
                for item in items[:2]:
                    if not isinstance(item, dict):
                        continue
                    source_id = (str(item.get("source_id") or "")).strip()
                    path = item.get("path_or_url") or item.get("url") or item.get("path")
                    path = (str(path) if path is not None else "").strip()
                    if not source_id or source_id not in allowed_source_ids:
                        continue
                    if not path or path not in allowed_image_paths:
                        continue
                    kept.append(
                        {
                            "source_id": source_id,
                            "path_or_url": path,
                            "caption_hint": (str(item.get("caption_hint") or item.get("alt") or "")).strip(),
                        }
                    )
                cleaned_images2[sec_id] = kept

            # 合并：保留空 list 的 key，便于下游统一遍历。
            for sec_id in required_ids:
                cleaned_images2.setdefault(sec_id, [])
            cleaned_images = cleaned_images2
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("researcher_select_images.failed error=%s", exc)

    # source_summaries：过滤非法 source_id，并补齐
    raw_summaries = output.source_summaries if isinstance(output.source_summaries, dict) else {}
    cleaned_summaries: Dict[str, str] = {}
    for key, value in raw_summaries.items():
        src_id = str(key)
        if src_id not in allowed_source_ids:
            continue
        if isinstance(value, str):
            cleaned_summaries[src_id] = value.strip()

    for src_id in allowed_source_ids:
        cleaned_summaries.setdefault(src_id, "")

    return (
        ResearcherOutput(
            section_notes=cleaned_notes,
            image_metadata=cleaned_images,
            source_summaries=cleaned_summaries,
        ),
        sorted(set(extra_keys)),
    )


def section_writer_agent(
    instruction: str,
    outline: Dict[str, Any],
    section_notes: Dict[str, str],
    image_metadata: Optional[Dict[str, List[Dict[str, Any]]]] = None,
    *,
    target_section_ids: Optional[List[str]] = None,
    existing_section_drafts: Optional[Dict[str, str]] = None,
    timeout_sec: float = 180.0,
) -> Dict[str, str]:
    """Section Writer：按小节生成 Markdown（每节独立生成，便于循环扩写）。"""

    section_notes = section_notes if isinstance(section_notes, dict) else {}
    image_metadata = image_metadata if isinstance(image_metadata, dict) else {}
    drafts: Dict[str, str] = dict(existing_section_drafts or {})

    sections = outline.get("sections") if isinstance(outline, dict) else None
    if not isinstance(sections, list) or not sections:
        return drafts

    target_set = set(target_section_ids or [])
    must_filter = bool(target_section_ids)

    system_prompt = f"""
你是 Section Writer 子 Agent，只负责撰写文章的一个小节。

【输入】
- instruction：整篇文章的写作目标、读者画像和语气要求（中文）。
- section_info：本节在大纲中的元信息：section_id、title、level、parent_id、is_core。
- notes：Researcher 为本节输出的“素材笔记”（可能是 NO_DATA 占位）。

【任务】
- 仅根据 section_info 和 notes 写出本节 Markdown 内容（不写其它小节）。
- 尽量用足 notes 中的有价值信息，但不得逐字长段复制，必须重写。

【输出格式】
你必须输出一个 JSON：
{{
  "section_id": "<与输入完全相同>",
  "markdown": "<从本节标题开始的 Markdown 内容>"
}}

markdown 字段要求：
- 第一行必须是正确级别的标题：
  - level=2 → "## 本节标题"
  - level=3 → "### 本节标题"
- 章节结构建议包含：简短引导 → 主体内容 → 小结（2-3 句）。
- 你需要在正文合适位置插入“插图占位符”，用于后续由 Illustrator 自动替换为真实图片并自动生成图注（图名）：
  - 占位符必须单独成行，格式之一：
    - `<!--IMAGE:<section_id>:<n>-->`（插入第 n 张图，n=1/2）
    - `<!--IMAGE:<section_id>:<n>|<图名/图注>-->`（同上，但你可提供更贴合上下文的图名/图注）
  - 其中 `<section_id>` 必须与本节 section_id 完全一致；`<n>` 为 1 或 2（最多两处插图）。
  - 你决定图片应该出现的位置：必须紧跟在解释该图的段落之后（概念解释/结构示意/流程描述/关键对比）。
  - 系统会额外给你本节的 `available_images`（候选图片列表，顺序即索引顺序，最多 2 张，含 caption_hint）：
    - 当 `available_images` 非空时：你必须至少插入 1 个占位符，并优先选择与你当前段落内容最匹配的那张（用 :1 或 :2 指定）。
    - 当 `available_images` 为空时：你不得插入任何占位符。

【篇幅 & 信息量】
- is_core=true：目标 800-1200 字，至少不低于 600 字。
- 普通小节：不应少于 400 字，尽量写到 600 字左右。
- 若 notes 为 NO_DATA：可以写一般性经验/注意点，但必须明确说明“下述内容基于通用经验，并非来自用户提供的资料”。

【禁止事项】
- 不得修改 section_id。
- 不得跨节写内容（只写当前 section）。
- 不得凭空杜撰具体的公司名称、真实项目、机密信息。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    structured_llm = build_structured_chat_llm(SectionDraftOutput, task_name="section_writer")

    for sec in sections:
        if not isinstance(sec, dict):
            continue
        section_id = str(sec.get("id") or "").strip()
        if not section_id:
            continue
        if must_filter and section_id not in target_set:
            continue

        title = str(sec.get("title") or "").strip() or section_id
        level = int(sec.get("level") or 2)
        if level not in (2, 3):
            level = 2

        notes = section_notes.get(section_id) or "NO_DATA: 本节在当前资料中未找到足够信息。"
        available_images = image_metadata.get(section_id) or []
        if not isinstance(available_images, list):
            available_images = []
        available_images = [img for img in available_images if isinstance(img, dict)]

        prompt_obj = {
            "instruction": instruction,
            "section_info": {
                "section_id": section_id,
                "title": title,
                "level": level,
                "parent_id": sec.get("parent_id"),
                "is_core": bool(sec.get("is_core")),
            },
            "notes": notes,
            # 只给出必要字段，避免 prompt 膨胀；并保留顺序，让 Writer 可用 :1/:2 指定图片。
            "available_images": [
                {
                    "path_or_url": (img.get("path_or_url") or img.get("url") or img.get("src") or ""),
                    "caption_hint": (img.get("caption_hint") or img.get("alt") or ""),
                }
                for img in available_images[:2]
                if (img.get("path_or_url") or img.get("url") or img.get("src"))
            ],
        }
        prompt = json.dumps(prompt_obj, ensure_ascii=False)

        def _call():
            return structured_llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt),
                ]
            )

        result = invoke_llm_with_timeout(
            task_name=f"section_writer_{section_id}",
            fn=_call,
            timeout_sec=timeout_sec,
        )
        output = result if isinstance(result, SectionDraftOutput) else SectionDraftOutput.model_validate(result)

        markdown = output.markdown or ""
        markdown = _strip_markdown_fence(markdown)
        markdown = _strip_reasoning_block(markdown)

        expected_heading = f"{'##' if level == 2 else '###'} {title}".strip()

        lines = markdown.splitlines()
        if not lines:
            markdown = expected_heading + "\n\n（本节内容生成失败，可稍后重试。）"
        else:
            first = lines[0].lstrip()
            if re.match(r"^#{1,6}\s+", first):
                lines[0] = expected_heading
                markdown = "\n".join(lines)
            else:
                markdown = expected_heading + "\n" + markdown

        drafts[section_id] = markdown.strip()

        _LOGGER.debug(
            "section_writer.done section_id=%s heading=%s len=%d",
            section_id,
            expected_heading,
            len(drafts[section_id]),
        )
        print(
            f"[section_writer] section_id={section_id} heading={expected_heading} len={len(drafts[section_id])}",
            flush=True,
        )

    return drafts


def doc_refiner_agent(
    outline: Dict[str, Any],
    draft_markdown: str,
    *,
    timeout_sec: float = 240.0,
) -> str:
    """Doc Refiner：在不改变标题结构的前提下通篇润色。"""

    if not draft_markdown:
        return draft_markdown

    system_prompt = f"""
你是 Doc Refiner 子 Agent，负责在不改变大纲结构的前提下，对整篇文章进行润色与微调。

【输入】
- outline：文章大纲（title + sections 列表），这是结构的权威来源。
- draft_markdown：当前完整草稿 Markdown。

【任务】
- 在完全保留现有标题和章节顺序的前提下：
  - 改善段落衔接和过渡句；
  - 删除明显重复的句子；
  - 统一术语和人称；
  - 轻微增强可读性（拆长句、合短句）。

【硬性结构约束（必须严格遵守）】
1. 严禁修改任何 Markdown 标题行：所有以 "#" / "##" / "###" 开头的标题行，文本必须与原稿完全一致。
2. 严禁增删标题，严禁改变标题级别，严禁调整标题出现顺序。
3. 严禁新增/删除整节内容；只能在每个现有小节内部调整句子与段落。
4. 严禁修改/删除/新增任何插图占位符：所有形如 `<!--IMAGE:...-->` 的行必须原封不动保留（内容与位置都不能变化）。

【输出】
- 只返回润色后的完整 Markdown 文本，不要输出任何额外文字或 JSON。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    llm = build_chat_llm(task_name="doc_refiner")
    prompt_obj = {"outline": outline, "draft_markdown": draft_markdown}
    prompt = json.dumps(prompt_obj, ensure_ascii=False)

    def _call():
        return llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )

    result = invoke_llm_with_timeout(task_name="doc_refiner", fn=_call, timeout_sec=timeout_sec)
    raw = getattr(result, "content", str(result))
    cleaned = _strip_markdown_fence(raw)
    cleaned = _strip_reasoning_block(cleaned)

    if not isinstance(cleaned, str) or not cleaned.strip():
        return draft_markdown

    if extract_markdown_headings(cleaned) != extract_markdown_headings(draft_markdown):
        _LOGGER.warning("doc_refiner.heading_mismatch fallback_to_draft")
        print("[doc_refiner] heading_mismatch fallback_to_draft", flush=True)
        return draft_markdown

    return cleaned.strip()


def illustrator_agent(
    final_markdown: str,
    outline: Dict[str, Any],
    image_metadata: Dict[str, List[Dict[str, Any]]],
    *,
    max_images_per_section: int = 2,
) -> str:
    """Illustrator：仅使用 image_metadata 中的原图，按 Writer 占位符替换插图（纯规则）。

    若正文中不存在占位符，则回退为“按章节末尾插入”，以保持兼容性。
    """

    if not final_markdown:
        return final_markdown
    if "<!--IMAGE:" in final_markdown:
        return replace_image_placeholders(
            markdown=final_markdown,
            image_metadata=image_metadata,
            max_images_per_section=max_images_per_section,
        )

    if not isinstance(image_metadata, dict) or not image_metadata:
        return final_markdown

    return insert_images_into_markdown(
        markdown=final_markdown,
        outline=outline,
        image_metadata=image_metadata,
        max_images_per_section=max_images_per_section,
    )


def assembler_agent(article_id: str, title: str, final_markdown: str) -> Dict[str, Any]:
    """Assembler：将 Markdown 落盘并返回 md_path/md_url 等信息。"""

    return export_markdown(article_markdown=final_markdown, title=title, article_id=article_id)


__all__ = [
    "collector_agent",
    "planner_agent",
    "researcher_agent",
    "section_writer_agent",
    "doc_refiner_agent",
    "illustrator_agent",
    "assembler_agent",
]
