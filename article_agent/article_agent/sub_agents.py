from __future__ import annotations

import json
import logging
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from langchain_core.messages import HumanMessage, SystemMessage

from concurrent.futures import ThreadPoolExecutor, as_completed

from .config import get_settings
from .llm_runtime import build_chat_llm, build_vlm_client, build_structured_chat_llm, invoke_llm_with_timeout, invoke_with_structured_thinking
from .prompts import COMMON_CONSTRAINTS_ZH
from .schema import ImageInsertionPlan, ImageSelectionOutput, OutlineOutput, ResearcherOutput, SectionDraftOutput, SectionReflectionOutput
from .tools_files import export_markdown, fetch_url_with_images, load_text_from_file
from .workflow_utils import extract_markdown_headings, insert_images_into_markdown, normalize_outline, replace_image_placeholders, compare_headings_lenient

_LOGGER = logging.getLogger("article_agent.sub_agents")

MAX_IMAGE_CANDIDATES_PER_SECTION = 8
MAX_IMAGES_PER_SECTION = MAX_IMAGE_CANDIDATES_PER_SECTION

# Qwen3 /nothink 指令前缀 - 设为空字符串以允许思维输出给前端显示
# 后端通过 _strip_reasoning_block 过滤思维内容
_NOTHINK_PREFIX = ""


def _with_nothink(prompt: str) -> str:
    """为 Qwen3 模型添加 /nothink 前缀，禁用思考模式。"""
    return _NOTHINK_PREFIX + prompt


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
    """去掉模型输出中的显式推理块（如 <think>...</think>）和泄露的思维过程。"""

    if not isinstance(text, str):
        return text

    # 1. 去掉 <think>...</think> 标签块
    cleaned = re.sub(r"<think[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    
    # 2. 去掉孤立的 </think> 标签（langchain 可能只去掉了开始标签）
    cleaned = re.sub(r"</think>", "", cleaned, flags=re.IGNORECASE)
    
    # 3. 去掉 qwen3 风格的思维过程泄露（中文）
    # 匹配以 "先看..." "首先..." "检查..." "接下来..." "现在开始..." 等开头的推理段落
    reasoning_patterns = [
        r"^先看用户.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "先看用户给的原文内容..."
        r"^首先，通读.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "首先，通读一遍原文..."
        r"^检查术语.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "检查术语是否统一..."
        r"^接下来，.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "接下来，看段落..."
        r"^现在逐段分析.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "现在逐段分析..."
        r"^这里.*?需要调整.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "这里...需要调整"
        r"^原[第一二三四五六七八九十]*段.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "原第一段..."
        r"^修改[后为].*?(?=\n\n|\n#{1,3}\s|\Z)",  # "修改后..."
        r"^删除重复.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "删除重复..."
        r"^现在开始.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "现在开始修改..."
        r"^现在，.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "现在，整合..."
        r"^最终检查.*?(?=\n\n|\n#{1,3}\s|\Z)",  # "最终检查..."
    ]
    
    for pattern in reasoning_patterns:
        cleaned = re.sub(pattern, "", cleaned, flags=re.MULTILINE | re.DOTALL)
    
    # 4. 去掉多余的连续空行
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    
    return cleaned.strip()


def analyze_images_with_vlm(
    images: List[Dict[str, Any]],
    section_title: str = "",
    section_notes: str = "",
    max_images: int = 5,
) -> List[Dict[str, Any]]:
    """使用 VLM 分析图片内容，返回增强后的图片元数据。
    
    Args:
        images: 原始图片列表，每个包含 path_or_url, alt 等
        section_title: 当前章节标题（用于相关性判断）
        section_notes: 当前章节笔记（用于相关性判断）
        max_images: 最多分析的图片数量（避免 VLM 调用过多）
    
    Returns:
        增强后的图片列表，每个增加 vlm_description, relevance_score 字段
    """
    settings = get_settings()
    
    if not getattr(settings, "vlm_enabled", True):
        _LOGGER.info("vlm_analyze.disabled")
        return images
    
    vlm = build_vlm_client(task_name="image_analyze")
    if vlm is None:
        _LOGGER.warning("vlm_analyze.client_not_available")
        return images
    
    # 只分析前 N 张图片
    images_to_analyze = images[:max_images]
    analyzed_images: List[Dict[str, Any]] = []
    
    for img in images_to_analyze:
        path_or_url = img.get("path_or_url") or img.get("url") or img.get("src") or ""
        if not path_or_url:
            analyzed_images.append(img)
            continue
        
        try:
            # 处理远程 URL：下载并转为 base64 data URL
            image_data_url = path_or_url
            if path_or_url.startswith(("http://", "https://")):
                try:
                    import base64
                    import requests
                    resp = requests.get(path_or_url, timeout=10, headers={
                        "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
                    })
                    if resp.status_code == 200:
                        content_type = resp.headers.get("Content-Type", "image/jpeg")
                        if ";" in content_type:
                            content_type = content_type.split(";")[0]
                        b64_data = base64.b64encode(resp.content).decode("utf-8")
                        image_data_url = f"data:{content_type};base64,{b64_data}"
                        
                        # 使用 PIL 获取图片尺寸
                        try:
                            from PIL import Image
                            import io
                            pil_image = Image.open(io.BytesIO(resp.content))
                            img_width, img_height = pil_image.size
                            img["width"] = img_width
                            img["height"] = img_height
                            _LOGGER.debug("vlm_analyze.downloaded image=%s size=%d dimensions=%dx%d", path_or_url[:50], len(resp.content), img_width, img_height)
                        except Exception as pil_exc:
                            _LOGGER.debug("vlm_analyze.pil_failed image=%s error=%s", path_or_url[:50], pil_exc)
                            _LOGGER.debug("vlm_analyze.downloaded image=%s size=%d", path_or_url[:50], len(resp.content))
                    else:
                        _LOGGER.warning("vlm_analyze.download_failed image=%s status=%d", path_or_url[:50], resp.status_code)
                        analyzed_images.append(img)
                        continue
                except Exception as dl_exc:
                    _LOGGER.warning("vlm_analyze.download_error image=%s error=%s", path_or_url[:50], dl_exc)
                    analyzed_images.append(img)
                    continue
            
            prompt = f"""请分析这张图片，输出 JSON 格式：
{{
  "description": "图片的详细描述（中文，50-100字）",
  "type": "diagram|chart|screenshot|photo|illustration|other",
  "key_elements": ["关键元素1", "关键元素2"],
  "suitable_topics": ["适合的文章主题"],
  "caption_suggestion": "建议的图片标题（中文）"
}}

章节标题：{section_title}
章节内容摘要：{section_notes[:500] if section_notes else '无'}

请根据图片内容和章节上下文，评估这张图片与该章节的相关性。"""

            messages = [
                HumanMessage(content=[
                    {"type": "image_url", "image_url": {"url": image_data_url}},
                    {"type": "text", "text": prompt},
                ])
            ]
            
            response = vlm.invoke(messages)
            vlm_content = response.content if hasattr(response, "content") else str(response)
            
            # 尝试解析 JSON
            try:
                # 提取 JSON 部分
                json_match = re.search(r"\{[\s\S]*\}", vlm_content)
                if json_match:
                    vlm_data = json.loads(json_match.group())
                else:
                    vlm_data = {"description": vlm_content}
            except json.JSONDecodeError:
                vlm_data = {"description": vlm_content}
            
            enhanced_img = {
                **img,
                "vlm_description": vlm_data.get("description", ""),
                "vlm_type": vlm_data.get("type", "other"),
                "vlm_key_elements": vlm_data.get("key_elements", []),
                "vlm_suitable_topics": vlm_data.get("suitable_topics", []),
                "vlm_caption": vlm_data.get("caption_suggestion", img.get("alt", "")),
            }
            analyzed_images.append(enhanced_img)
            
            _LOGGER.info(
                "vlm_analyze.success image=%s type=%s",
                path_or_url[:50],
                enhanced_img.get("vlm_type"),
            )
            
        except Exception as exc:
            _LOGGER.warning("vlm_analyze.failed image=%s error=%s", path_or_url[:50], exc)
            analyzed_images.append(img)
    
    # 保留未分析的图片（原样返回）
    for img in images[max_images:]:
        analyzed_images.append(img)
    
    return analyzed_images


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
            # 调试日志：显示收集到的内容摘要
            _LOGGER.info("collector.url_fetched source_id=%s url=%s title=%s snippet_len=%d images=%d",
                        source_id, url[:50], data.get("title", "")[:50], len(snippet), len(images) if isinstance(images, list) else 0)
            print(f"[collector] {source_id}: {data.get('title', '')[:60]} | {len(text)} chars | {len(images) if isinstance(images, list) else 0} images", flush=True)
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

【核心原则 - 极其重要】
**文章主题必须完全基于 rough_sources_overview 中的实际内容！**
- 你必须仔细阅读 rough_sources_overview 中每个来源的 rough_snippet（内容概览）
- 文章标题和章节必须围绕这些来源的实际内容来设计
- **严禁**生成与 rough_sources_overview 内容无关的主题
- 如果来源内容是关于 Transformer 的，文章就必须是关于 Transformer 的
- 如果来源内容是关于机器学习的，文章就必须是关于机器学习的

【任务目标】
1. **首先分析 rough_sources_overview**，理解用户提供的来源实际讲什么内容。
2. 基于来源内容和 instruction（用户偏好），为文章设计结构清晰、层级明确的大纲。
3. 输出文章总标题 title（必须反映来源内容的主题）。
4. 输出 sections 列表，每个 section 包含：
   - id：小写字母 + 下划线组成的唯一字符串，如 "sec_intro"。
   - title：该节标题。
   - level：数字 2 或 3，表示 Markdown 的 ## 或 ### 级别。
   - parent_id：可选。若为三级标题，指向所属二级标题的 id。
   - is_core：布尔值，是否为核心内容部分。
   - target_word_count：该小节的目标字数（整数，根据用户总字数要求计算）。
5. 输出 sections_to_research：需要 Researcher 重点研究的 section_id 列表（只列 id）。
6. 输出 writing_style：根据 instruction 和概览，为 Writer 总结的写作风格指导（语气、受众、用词规范等）。

【字数分配规则 - 非常重要】
1. 首先从 instruction 中解析用户要求的总字数（如"5000字"、"5000-6000字"等）。
2. 如果没有明确字数要求，默认总字数为 3000 字。
3. 根据总字数和 section 数量，合理分配每个 section 的 target_word_count：
   - 核心 section (is_core=true)：分配 1.5 倍权重
   - 引言/总结：分配 0.7 倍权重
   - 普通 section：分配 1.0 倍权重
4. 确保所有 section 的 target_word_count 之和约等于用户要求的总字数。
5. 每个 section 的 target_word_count 最低不少于 200 字，最高不超过 800 字。

【输出格式】
你必须输出一个 JSON：
{{
  "title": "文章标题",
  "sections": [
    {{"id": "sec_intro", "title": "背景与目标", "level": 2, "parent_id": null, "is_core": false, "target_word_count": 350}}
  ],
  "sections_to_research": ["sec_intro"],
  "writing_style": "语气专业客观，面向中高级开发者，多用技术术语。"
}}

【Few-shot 示例】

✅ 好的大纲结构（用户要求5000字）：
{{
  "title": "Python 异步编程完全指南",
  "sections": [
    {{"id": "sec_intro", "title": "异步编程概述", "level": 2, "parent_id": null, "is_core": false, "target_word_count": 400}},
    {{"id": "sec_asyncio_basics", "title": "asyncio 核心概念", "level": 2, "parent_id": null, "is_core": true, "target_word_count": 700}},
    {{"id": "sec_event_loop", "title": "事件循环机制", "level": 3, "parent_id": "sec_asyncio_basics", "is_core": false, "target_word_count": 600}},
    {{"id": "sec_coroutines", "title": "协程与任务", "level": 3, "parent_id": "sec_asyncio_basics", "is_core": false, "target_word_count": 600}},
    {{"id": "sec_patterns", "title": "常见异步模式", "level": 2, "parent_id": null, "is_core": true, "target_word_count": 700}},
    {{"id": "sec_concurrency", "title": "并发任务管理", "level": 3, "parent_id": "sec_patterns", "is_core": false, "target_word_count": 550}},
    {{"id": "sec_errors", "title": "异常处理", "level": 3, "parent_id": "sec_patterns", "is_core": false, "target_word_count": 500}},
    {{"id": "sec_summary", "title": "总结与最佳实践", "level": 2, "parent_id": null, "is_core": false, "target_word_count": 350}}
  ],
  "sections_to_research": ["sec_asyncio_basics", "sec_patterns"],
  "writing_style": "面向有Python基础的开发者，用词简洁，结合代码示例。"
}}
// 上述8个section的target_word_count之和 = 4400字，接近用户要求的5000字

❌ 不好的大纲结构（问题示例）：
{{
  "title": "异步编程",  // 标题过于简略
  "sections": [
    {{"id": "intro", "title": "引言", "level": 2, "parent_id": null, "is_core": true}},  // id缺少sec_前缀
    {{"id": "sec_detail", "title": "详细解析", "level": 2, "parent_id": null, "is_core": true}},  // 太泛，无具体内容指向
    {{"id": "sec_code", "title": "代码示例", "level": 3, "parent_id": "wrong_parent", "is_core": false}},  // parent_id错误
    {{"id": "sec_summary", "title": "总结", "level": 2, "parent_id": null, "is_core": false}},
    {{"id": "sec_detail_1", "title": "深入理解", "level": 3, "parent_id": "sec_summary", "is_core": false}}  // 总结section不应有子章节
  ],
  "sections_to_research": ["sec_unknown"],  // 引用不存在的section
  "writing_style": "专业"  // 过于简略，缺少具体指导
}}

【约束】
- 所有 section.id 必须全局唯一。
- sections_to_research 中的所有 id 必须来自 sections 列表中的 id。
- 大纲应兼顾“背景/问题 → 架构/流程 → 关键实现 → 实践建议/案例 → 总结展望”的结构。
- 禁止生成“附录”、“参考文献”、“扩展阅读”等辅助性章节，文章应直接结束于核心内容或总结。
- 禁止生成技术标记类section：不得出现“插图占位符”、“图片”、“示例代码”、“格式说明”等作为section标题（这些是技术实现细节，不是文章内容）。
- “总结”、“结论”、“展望”类section（level=2）不得有子章节（level=3），应该是扁平的概括性内容，不再深入技术细节。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    prompt_obj = {"instruction": instruction, "rough_sources_overview": rough_sources_overview}
    prompt = json.dumps(prompt_obj, ensure_ascii=False)

    # 使用支持思维模式的结构化输出
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]
    
    thinking, result = invoke_with_structured_thinking(
        messages=messages,
        output_model=OutlineOutput,
        task_name="planner",
        timeout_sec=600.0,  # VLM 模型需要更长超时时间
    )
    
    # 记录思维过程到日志（后续可以通过 adispatch_custom_event 发送给前端）
    if thinking:
        _LOGGER.info("planner_agent.thinking len=%d preview=%s", len(thinking), thinking[:200])
    
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

    # 使用支持思维模式的结构化输出
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=prompt),
    ]
    
    thinking, result = invoke_with_structured_thinking(
        messages=messages,
        output_model=ResearcherOutput,
        task_name="researcher",
        timeout_sec=timeout_sec,
    )
    
    # 记录思维过程
    if thinking:
        _LOGGER.info("researcher_agent.thinking len=%d preview=%s", len(thinking), thinking[:200])
    
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
- 每个 section 最多选择 {MAX_IMAGE_CANDIDATES_PER_SECTION} 张图片作为候选（后续 Writer 会再从候选中挑选 1-2 张插入正文）。

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
                    SystemMessage(content=_with_nothink(image_system_prompt)),
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
                for item in items[: MAX_IMAGE_CANDIDATES_PER_SECTION]:
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

    # VLM 图片分析：对每个 section 的候选图片进行语义分析
    settings = get_settings()
    if getattr(settings, "vlm_enabled", False):
        _LOGGER.info("researcher_agent.vlm_analysis_start sections=%d", len(cleaned_images))
        
        for sec_id, images in cleaned_images.items():
            if not images:
                continue
            
            # 获取 section 信息用于相关性判断
            sec_title = ""
            for sec in (outline.get("sections") or []):
                if isinstance(sec, dict) and sec.get("id") == sec_id:
                    sec_title = sec.get("title", "")
                    break
            
            sec_notes = cleaned_notes.get(sec_id, "")
            
            # 调用 VLM 分析
            try:
                analyzed = analyze_images_with_vlm(
                    images=images,
                    section_title=sec_title,
                    section_notes=sec_notes,
                    max_images=3,  # 每个 section 最多分析 3 张
                )
                cleaned_images[sec_id] = analyzed
                _LOGGER.info("researcher_agent.vlm_analysis_done section=%s images=%d", sec_id, len(analyzed))
            except Exception as vlm_exc:
                _LOGGER.warning("researcher_agent.vlm_analysis_failed section=%s error=%s", sec_id, vlm_exc)

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
    timeout_sec: float = 300.0,  # VLM 模型需要更长超时时间
    on_section_complete: Optional[Callable[[str, str, int], None]] = None,  # (section_id, title, char_count)
) -> Dict[str, str]:
    """Section Writer：按小节生成 Markdown（每节独立生成，便于循环扩写）。
    
    Args:
        on_section_complete: 可选回调，每完成一个章节后调用，参数为 (section_id, title, char_count)
    """

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
- writing_style：Planner 统一制定的写作风格指导（语气、受众、用词规范等）。
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
- 章节结构：简短引导 → 主体内容（充实展开）→ 自然结束（不要添加小结、总结、综上所述等总结性段落）。
- **数学公式使用 LaTeX 语法（JSON 中反斜杠必须双写）**：
  - **重要**：因为你输出的是 JSON 格式，所有反斜杠必须写成双反斜杠 `\\\\` 才能在最终 Markdown 中保留为单反斜杠 `\\`。
  - 行内公式：用单个美元符号，例如 `$Q = XW_Q$` 或 `$d_k$`
  - 块级公式：用双美元符号，**前后各空一行，公式另起一行**：
    ```
    前一段。
    
    $$
    Q = XW_Q
    $$
    
    后一段。
    ```
  - 常用 LaTeX 命令（JSON中必须双反斜杠）：
    - 希腊字母：`\\\\alpha`、`\\\\beta`、`\\\\gamma`
    - 求和/积分：`\\\\sum_{{i=1}}^{{n}}`、`\\\\int_{{a}}^{{b}}`
    - 分数：`\\\\frac{{分子}}{{分母}}`，示例：`\\\\frac{{QK^T}}{{\\\\sqrt{{d_k}}}}`
    - 文本：`\\\\text{{注意力}}`
  - 多公式对齐（aligned环境）：
    ```
    $$
    \\\\begin{{aligned}}
    Q &= XW_Q \\\\\\\\
    K &= XW_K \\\\\\\\
    V &= XW_V
    \\\\end{{aligned}}
    $$
    ```

【图片说明】
- **你不需要处理图片**。专注于文字内容的撰写。
- 图片将由 Illustrator Agent 在后续步骤中根据你的内容自动匹配并插入。
- 不要插入任何图片占位符（如 `<!--IMAGE:...-->`）。

【篇幅 & 信息量】
- **目标字数**：请参考 section_info 中的 target_word_count 字段，这是 Planner 根据用户总字数要求分配的。
- 如果 target_word_count 未提供，默认按以下规则：
  - is_core=true：目标 600-800 字
  - 普通小节：目标 400-600 字
- **严格遵守目标字数**：不要显著超过或低于目标字数（允许±20%浮动）。
- 若 notes 为 NO_DATA：可以写一般性经验/注意点，但必须明确说明"下述内容基于通用经验，并非来自用户提供的资料"。

【禁止事项】
- 不得修改 section_id。
- 不得跨节写内容（只写当前 section）。
- 不得凭空杜撰具体的公司名称、真实项目、机密信息。
- **禁止添加任何形式的小结或技术标记类标题**：
  - ❌ 不得添加"### 小结"、"### 本节总结"、"### 要点回顾"等总结性标题
  - ❌ 不得添加"### 插图占位符"、"### 代码示例"、"### 格式说明"等技术实现类标题
  - ❌ 不得添加除大纲规定之外的任何二级或三级标题
  - ✅ 你只能写大纲中给定section的标题和正文内容
- **禁止手动编号**：
  - ❌ 不得在标题中添加"1. 2. 3."等编号（如"### 1. 基本概念"是错误的）
  - ❌ 不得在段落开头添加"第一、第二、（1）（2）"等编号形式
  - ✅ 标题编号由系统自动添加，你只需写标题文字本身
- 可以适当使用"综上所述"、"因此"等连接词进行段落过渡或逻辑归纳（这是自然的写作手法）。

{COMMON_CONSTRAINTS_ZH}
""".strip()

    settings = get_settings()
    max_workers = getattr(settings, "max_worker_threads", 5)

    # 不再使用 build_structured_chat_llm，改用 invoke_with_structured_thinking 支持思维模式

    def _process_section(sec: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        if not isinstance(sec, dict):
            return None
        section_id = str(sec.get("id") or "").strip()
        if not section_id:
            return None
        if must_filter and section_id not in target_set:
            return None

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
            "writing_style": str(outline.get("writing_style") or ""),
            "section_info": {
                "section_id": section_id,
                "title": title,
                "level": level,
                "parent_id": sec.get("parent_id"),
                "is_core": bool(sec.get("is_core")),
                "target_word_count": int(sec.get("target_word_count") or 500),
            },
            "notes": notes,
            # 传递图片信息给Writer，包含上下文帮助其做出更好的选择
            "available_images": [
                {
                    "path_or_url": (img.get("path_or_url") or img.get("url") or img.get("src") or ""),
                    "caption_hint": (img.get("caption_hint") or img.get("alt") or ""),
                    "context": (img.get("context") or ""),  # 新增：图片周围的文本上下文
                }
                for img in available_images[:MAX_IMAGE_CANDIDATES_PER_SECTION]
                if (img.get("path_or_url") or img.get("url") or img.get("src"))
            ],
        }
        prompt = json.dumps(prompt_obj, ensure_ascii=False)

        # 使用支持思维模式的结构化输出
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]

        try:
            thinking, output = invoke_with_structured_thinking(
                messages=messages,
                output_model=SectionDraftOutput,
                task_name=f"section_writer_{section_id}",
                timeout_sec=timeout_sec,
            )
            
            # 记录思维过程
            if thinking:
                _LOGGER.info("section_writer.thinking section=%s len=%d", section_id, len(thinking))
            
            markdown = output.markdown or ""
        except Exception as exc:
            _LOGGER.warning("section_writer_task_failed section_id=%s error=%s", section_id, exc)
            markdown = ""

        markdown = _strip_markdown_fence(markdown)
        # 保留思维内容用于流式展示，最终在 assembler 清理
        # markdown = _strip_reasoning_block(markdown)

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

        final_draft = markdown.strip()

        # 兜底：当本节有可用图片，但模型未给出任何占位符时，插入一个默认占位符。
        if prompt_obj.get("available_images") and f"<!--IMAGE:{section_id}" not in final_draft:
            lines2 = final_draft.splitlines()
            if lines2:
                insert_at = len(lines2)
                # 尽量插在标题后的第一个自然段后
                i = 1
                while i < len(lines2) and not lines2[i].strip():
                    i += 1
                while i < len(lines2) and lines2[i].strip():
                    i += 1
                insert_at = i if i > 1 else 1
                insertion = ["", f"<!--IMAGE:{section_id}:1-->", ""]
                lines2 = lines2[:insert_at] + insertion + lines2[insert_at:]
                final_draft = "\n".join(lines2).strip()

        _LOGGER.debug(
            "section_writer.done section_id=%s heading=%s len=%d",
            section_id,
            expected_heading,
            len(final_draft),
        )
        print(
            f"[section_writer] section_id={section_id} heading={expected_heading} len={len(final_draft)}",
            flush=True,
        )
        return section_id, final_draft

    # 构建 section_id -> title 映射，用于回调
    section_titles = {}
    for sec in sections:
        if isinstance(sec, dict):
            sec_id = str(sec.get("id") or "").strip()
            sec_title = str(sec.get("title") or "").strip() or sec_id
            if sec_id:
                section_titles[sec_id] = sec_title
    
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [executor.submit(_process_section, sec) for sec in sections]
        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    sec_id, txt = res
                    drafts[sec_id] = txt
                    # 调用回调通知完成
                    if on_section_complete:
                        title = section_titles.get(sec_id, sec_id)
                        on_section_complete(sec_id, title, len(txt))
            except Exception as exc:
                _LOGGER.error("section_writer.future_failed error=%s", exc)

    return drafts


def reflect_section_agent(
    section_id: str,
    section_title: str,
    section_draft: str,
    instruction: str,
    notes: str = "",
    *,
    timeout_sec: float = 90.0,
) -> SectionReflectionOutput:
    """反思一个章节的质量，输出评分和改进建议。
    
    Args:
        section_id: 章节 ID
        section_title: 章节标题
        section_draft: 章节草稿内容
        instruction: 用户的写作指令
        notes: Researcher 提供的原始笔记
        timeout_sec: 超时时间
    
    Returns:
        SectionReflectionOutput 包含质量评分和修改建议
    """
    
    system_prompt = f"""你是 Reflection Agent，负责评估文章章节的质量并提供改进建议。

【任务】
评估给定章节是否达到发布标准，并输出结构化的反思结果。

【评估维度】
1. 信息完整性：是否充分利用了笔记中的关键信息
2. 逻辑连贯性：段落之间是否有清晰的逻辑关系
3. 语言表达：是否通顺、专业、无语病
4. 符合指令：是否符合用户的写作要求
5. 字数要求：是否达到目标字数

【评分标准】
- 9-10分：优秀，可直接发布
- 7-8分：良好，小瑕疵可接受
- 5-6分：一般，需要修改
- 1-4分：差，需要重写

【输出格式】
你必须输出 JSON：
{{
  "section_id": "章节ID",
  "quality_score": 1-10的整数,
  "issues": [
    {{"issue": "问题描述", "suggestion": "修改建议"}}
  ],
  "strengths": ["优点1", "优点2"],
  "needs_revision": true/false,
  "revision_focus": "如需修改，重点关注什么"
}}

【约束】
- 7分以上设 needs_revision=false
- 6分及以下设 needs_revision=true
- issues 至少列出发现的问题（即使分数高也要指出可改进之处）

{COMMON_CONSTRAINTS_ZH}
""".strip()

    prompt_obj = {
        "instruction": instruction,
        "section_id": section_id,
        "section_title": section_title,
        "section_draft": section_draft,
        "original_notes": notes[:2000] if notes else "",
    }
    prompt = json.dumps(prompt_obj, ensure_ascii=False)

    structured_llm = build_structured_chat_llm(SectionReflectionOutput, task_name="reflect_section")

    def _call():
        return structured_llm.invoke(
            [
                SystemMessage(content=_with_nothink(system_prompt)),
                HumanMessage(content=prompt),
            ]
        )

    try:
        result = invoke_llm_with_timeout(
            task_name=f"reflect_section_{section_id}",
            fn=_call,
            timeout_sec=timeout_sec,
        )
        output = result if isinstance(result, SectionReflectionOutput) else SectionReflectionOutput.model_validate(result)
        
        _LOGGER.info(
            "reflect_section.done section_id=%s score=%d needs_revision=%s",
            section_id,
            output.quality_score,
            output.needs_revision,
        )
        return output
        
    except Exception as exc:
        _LOGGER.warning("reflect_section.failed section_id=%s error=%s", section_id, exc)
        # 返回默认通过结果，避免阻塞流程
        return SectionReflectionOutput(
            section_id=section_id,
            quality_score=7,
            issues=[],
            strengths=[],
            needs_revision=False,
            revision_focus="",
        )


def reader_review_agent(
    instruction: str,
    draft_markdown: str,
    outline: Dict[str, Any],
    *,
    timeout_sec: float = 240.0,
) -> "ReaderReviewOutput":
    """Reader Review：从读者视角审阅草稿，指出问题章节并提出改进建议。
    
    Returns:
        ReaderReviewOutput: 包含 feedback、sections_to_rewrite 和 quality_ok
    """
    from .schema import ReaderReviewOutput

    if not draft_markdown:
        return ReaderReviewOutput(feedback="", sections_to_rewrite=[], quality_ok=True)

    # 提取所有章节 ID 供 LLM 参考
    sections = outline.get("sections", []) if isinstance(outline, dict) else []
    section_ids = [str(sec.get("id", "")) for sec in sections if isinstance(sec, dict) and sec.get("id")]
    sections_info = [
        {"id": sec.get("id"), "title": sec.get("title"), "level": sec.get("level")}
        for sec in sections if isinstance(sec, dict)
    ]

    system_prompt = f"""
你是 Reader Review 子 Agent，代表目标读者对文章草稿进行审阅。

【输入】
- instruction：文章的原始写作目标、受众和预期语气。
- draft_markdown：当前生成的文章草稿。
- sections_info：文章的章节结构（包含 id、title、level）。

【任务】
1. 扮演 instruction 中描述的最典型的目标读者。
2. 通读 draft_markdown，从"可读性"、"有用性"、"是否解决问题"三个维度进行评价。
3. 识别有明显问题的章节（使用 sections_info 中的 id）：
   - 内容过短或空洞
   - 逻辑断层或跳跃
   - 晦涩难懂或缺乏解释
   - 与主题不相关
4. 给出 3-5 条具体的改进建议。

【输出格式】
输出 JSON 格式，包含：
- feedback：审阅意见（300字以内）
- sections_to_rewrite：需要重写的 section_id 列表
  - 只列出确实有严重问题需要重写的章节
  - 如果文章整体质量良好，返回空列表 []
- quality_ok：布尔值，文章整体是否可接受

【可用的 section_id 列表】
{json.dumps(section_ids, ensure_ascii=False)}

【重要】
- 只返回确实需要重写的章节，不要随意列出所有章节
- 如果文章质量良好，sections_to_rewrite 应为空列表
- 最多列出 3 个需要重写的章节

{COMMON_CONSTRAINTS_ZH}
""".strip()

    prompt = json.dumps(
        {
            "instruction": instruction,
            "draft_preview": draft_markdown[:15000],
            "sections_info": sections_info,
        },
        ensure_ascii=False,
    )

    try:
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]
        
        _thinking, result = invoke_with_structured_thinking(
            messages=messages,
            output_model=ReaderReviewOutput,
            task_name="reader_review",
            timeout_sec=timeout_sec,
        )
        
        _LOGGER.info("reader_review.success sections_to_rewrite=%s quality_ok=%s",
                    result.sections_to_rewrite, result.quality_ok)
        return result
    except Exception as exc:
        _LOGGER.warning("reader_review.failed error=%s", exc)
        return ReaderReviewOutput(feedback=f"审阅失败：{exc}", sections_to_rewrite=[], quality_ok=True)


def doc_refiner_agent(
    outline: Dict[str, Any],
    draft_markdown: str,
    *,
    timeout_sec: float = 240.0,
) -> str:
    """Doc Refiner：在不改变标题结构的前提下通篇润色。"""

    if not draft_markdown:
        return draft_markdown

    # 按章节拆分文章
    lines = draft_markdown.split("\n")
    sections: List[Dict[str, Any]] = []  # [{start, end, heading, content}]
    current_section_start = 0
    current_heading = ""
    
    for i, line in enumerate(lines):
        if re.match(r"^#{1,3}\s+", line.strip()):
            if current_heading:
                sections.append({
                    "start": current_section_start,
                    "end": i,
                    "heading": current_heading,
                    "content": "\n".join(lines[current_section_start:i]),
                })
            current_section_start = i
            current_heading = line.strip()
    
    # 最后一个章节
    if current_heading:
        sections.append({
            "start": current_section_start,
            "end": len(lines),
            "heading": current_heading,
            "content": "\n".join(lines[current_section_start:]),
        })
    
    if not sections:
        return draft_markdown
    
    # 按章节润色
    system_prompt = f"""你是 Doc Refiner，负责润色一个章节的正文。

【任务】
只润色正文段落，**绝对禁止修改标题行**：
- 改善段落衔接和过渡
- 删除重复句子
- 统一术语
- 提高可读性

【⚠️ 硬性约束】
1. 第一行的标题（以 # 开头）必须**原封不动**保留
2. 不得新增或删除任何标题
3. 只输出润色后的章节内容，不要解释

{COMMON_CONSTRAINTS_ZH}
""".strip()

    llm = build_chat_llm(task_name="doc_refiner")
    refined_sections: List[str] = []
    success_count = 0
    
    for sec in sections:
        heading = sec["heading"]
        content = sec["content"]
        
        # 跳过太短的章节（只有标题）
        if content.strip() == heading.strip():
            refined_sections.append(content)
            continue
        
        try:
            def _call():
                return llm.invoke([
                    SystemMessage(content=_with_nothink(system_prompt)),
                    HumanMessage(content=f"请润色以下章节内容：\n\n{content}"),
                ])
            
            result = invoke_llm_with_timeout(task_name="doc_refiner", fn=_call, timeout_sec=60.0)
            raw = getattr(result, "content", str(result))
            cleaned = _strip_markdown_fence(raw)
            cleaned = _strip_reasoning_block(cleaned)
            
            if not cleaned or not cleaned.strip():
                refined_sections.append(content)
                continue
            
            # 强制保留原始第一行标题（防止LLM修改标题级别）
            original_lines = content.strip().split('\n')
            refined_lines = cleaned.strip().split('\n')
            
            if original_lines and refined_lines:
                # 检查原始第一行是否为标题
                if original_lines[0].strip().startswith('#'):
                    # 强制用原始标题替换refined的第一行
                    refined_lines[0] = original_lines[0]
                    cleaned = '\n'.join(refined_lines)
            
            # 验证所有标题未被新增或删除
            original_headings = extract_markdown_headings(content)
            refined_headings = extract_markdown_headings(cleaned)
            
            if original_headings and refined_headings:
                # 检查标题数量是否一致
                if len(original_headings) == len(refined_headings):
                    refined_sections.append(cleaned.strip())
                    success_count += 1
                else:
                    _LOGGER.warning("doc_refiner.section_heading_count_changed section=%r orig=%d refined=%d", 
                                   heading[:30], len(original_headings), len(refined_headings))
                    refined_sections.append(content)
            else:
                refined_sections.append(cleaned.strip() if cleaned else content)
                if cleaned:
                    success_count += 1
                
        except Exception as exc:
            _LOGGER.warning("doc_refiner.section_error section=%r error=%s", heading[:30], exc)
            refined_sections.append(content)
    
    print(f"[doc_refiner] per-section: {success_count}/{len(sections)} sections refined", flush=True)
    return "\n\n".join(refined_sections)


def illustrator_agent(
    final_markdown: str,
    outline: Dict[str, Any],
    all_images: List[Dict[str, Any]],
    *,
    max_images_total: int = 5,
    timeout_sec: float = 300.0,  # VLM 模型需要更长超时时间
) -> str:
    """Illustrator：使用 LLM 智能匹配图片与文章内容，并在最佳位置插入图片。
    
    Args:
        final_markdown: 完整的文章 Markdown（无占位符）
        outline: 文章大纲
        all_images: 所有候选图片列表，每个包含 {url, alt, context, figcaption}
        max_images_total: 全文最多插入的图片数量
        timeout_sec: LLM 调用超时
        
    Returns:
        插入了图片的最终 Markdown
    """
    if not final_markdown:
        return final_markdown
    
    if not all_images:
        return final_markdown
    
    # 过滤有效图片
    valid_images = [
        img for img in all_images
        if img.get("url") or img.get("src") or img.get("path_or_url")
    ][:max_images_total * 2]  # 预留更多供选择
    
    if not valid_images:
        return final_markdown
    
    # 构建图片信息摘要
    images_info = []
    for i, img in enumerate(valid_images):
        url = img.get("url") or img.get("src") or img.get("path_or_url") or ""
        caption = img.get("figcaption") or img.get("caption_hint") or img.get("alt") or ""
        context = img.get("context") or ""
        images_info.append({
            "index": i + 1,
            "url": url,
            "caption": caption,
            "context": context[:200],  # 限制长度
        })
    
    # 提取文章各section的内容摘要
    sections_info = []
    lines = final_markdown.split("\n")
    current_section = None
    current_content = []
    
    for line in lines:
        if re.match(r"^#{2,3}\s+", line):
            if current_section:
                sections_info.append({
                    "heading": current_section,
                    "content_preview": " ".join(current_content)[:300],
                })
            current_section = line.strip()
            current_content = []
        elif current_section and line.strip():
            current_content.append(line.strip())
    
    if current_section:
        sections_info.append({
            "heading": current_section,
            "content_preview": " ".join(current_content)[:300],
        })
    
    if not sections_info:
        return final_markdown
    
    # LLM Prompt
    system_prompt = f"""你是 Illustrator Agent，负责为技术文章智能配图。

【任务】
分析文章各章节内容和候选图片的描述，找出最佳的图文匹配关系，并决定图片应该插入到哪个段落之后。

【输入】
1. sections：文章各章节的标题和内容摘要
2. images：候选图片列表（含 index, caption, context）

【输出要求】
输出一个 JSON，指定哪些图片应该插入到哪里：
{{
  "insertions": [
    {{
      "image_index": 1,
      "target_heading": "## 2. 自注意力机制",
      "insert_after_text": "通过计算查询向量与键向量的点积",
      "reason": "该图展示了注意力权重计算，紧跟在描述点积计算的段落后最合适"
    }}
  ]
}}

【字段说明】
- image_index: 图片在候选列表中的索引（1-based）
- target_heading: 目标章节的标题
- insert_after_text: **关键字段** - 图片应插入在哪段文字之后。提供该段落的前20-30个字作为定位依据。如果放在章节开头，留空。
- reason: 为什么选择这个位置

【匹配规则】
1. 只有当图片内容与**某段文字高度相关**时才插入
2. 根据图片的 context 和 caption 判断其真实内容
3. 图片应该紧跟在**解释该图的段落之后**（概念解释/结构示意/流程描述）
4. 每个章节最多插入 1 张图片
5. 全文最多插入 {max_images_total} 张图片

【禁止】
- 不要编造图片信息
- 不要强行匹配不相关的图片
- 不要把图片放在章节开头（除非整个章节都在描述这张图）

{COMMON_CONSTRAINTS_ZH}
"""

    prompt_obj = {
        "sections": sections_info,
        "images": images_info,
    }
    prompt = json.dumps(prompt_obj, ensure_ascii=False)
    
    try:
        # 使用 invoke_with_structured_thinking 确保可靠的 JSON 解析
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]
        
        _thinking, result = invoke_with_structured_thinking(
            messages=messages,
            output_model=ImageInsertionPlan,
            task_name="illustrator",
            timeout_sec=timeout_sec,
        )
        plan = result if isinstance(result, ImageInsertionPlan) else ImageInsertionPlan.model_validate(result)
        
        if not plan.insertions:
            return final_markdown
        
        # 执行插入
        used_images: set = set()
        result_lines = final_markdown.split("\n")
        
        # 收集插入计划
        insertion_plans: List[Dict] = []
        for ins in plan.insertions:
            idx = ins.image_index
            heading = ins.target_heading
            insert_after = getattr(ins, "insert_after_text", "") or ""
            if idx in used_images:
                continue
            if idx < 1 or idx > len(valid_images):
                continue
            used_images.add(idx)
            insertion_plans.append({
                "image": valid_images[idx - 1],
                "heading": heading,
                "insert_after": insert_after.strip(),
            })
            if len(used_images) >= max_images_total:
                break
        
        # 基于内容匹配查找插入位置
        insert_positions: List[Tuple[int, str]] = []  # (line_index, img_html)
        img_counter = 0
        
        for plan_item in insertion_plans:
            target_heading = plan_item["heading"]
            insert_after = plan_item["insert_after"]
            img = plan_item["image"]
            
            # 找到目标section的起止范围
            section_start = -1
            section_end = len(result_lines)
            
            # 提取标题文字（去掉 ## 和编号）用于模糊匹配
            def extract_heading_text(h: str) -> str:
                """从标题中提取纯文字部分，去掉 ## 和编号"""
                h = h.strip()
                if h.startswith("### "):
                    h = h[4:]
                elif h.startswith("## "):
                    h = h[3:]
                elif h.startswith("# "):
                    h = h[2:]
                # 去掉开头的编号（如 "1." "2.1" 等）
                h = re.sub(r'^\d+(\.\d+)*\.?\s*', '', h)
                return h.strip()
            
            target_text = extract_heading_text(target_heading)
            
            for i, line in enumerate(result_lines):
                line_stripped = line.strip()
                
                # 只匹配标题行
                if not (line_stripped.startswith("## ") or line_stripped.startswith("### ") or line_stripped.startswith("# ")):
                    continue
                
                # 完全匹配
                if line_stripped == target_heading:
                    section_start = i
                    break
                
                # 文字内容匹配（忽略编号）
                line_text = extract_heading_text(line_stripped)
                if line_text == target_text:
                    section_start = i
                    break
                
                # 文字部分包含匹配（target在line中）
                if target_text and target_text in line_text:
                    section_start = i
                    break
            
            if section_start == -1:
                _LOGGER.warning("illustrator: heading not found: %s", target_heading)
                continue  # 未找到目标section
            
            # 找到下一个同级或更高级标题作为section结束
            for j in range(section_start + 1, len(result_lines)):
                if result_lines[j].startswith("## ") or result_lines[j].startswith("# "):
                    section_end = j
                    break
            
            # 在section范围内查找 insert_after 文本
            insert_line = section_start + 1  # 默认: section标题后
            
            if insert_after:
                # 模糊匹配：查找包含 insert_after 前30个字的段落
                search_text = insert_after[:30].strip()
                found = False
                for i in range(section_start + 1, section_end):
                    if search_text in result_lines[i]:
                        # 找到这个段落的末尾
                        j = i + 1
                        while j < section_end and result_lines[j].strip() and not result_lines[j].startswith("#"):
                            j += 1
                        insert_line = j
                        found = True
                        break
                if not found:
                    # 未找到匹配文本，插入在第一段之后
                    j = section_start + 1
                    while j < section_end and not result_lines[j].strip():
                        j += 1
                    while j < section_end and result_lines[j].strip() and not result_lines[j].startswith("#"):
                        j += 1
                    insert_line = j
            else:
                # 没有 insert_after，插入在第一段之后
                j = section_start + 1
                while j < section_end and not result_lines[j].strip():
                    j += 1
                while j < section_end and result_lines[j].strip() and not result_lines[j].startswith("#"):
                    j += 1
                insert_line = j
            
            # 构建图片 HTML
            img_url = img.get("url") or img.get("src") or img.get("path_or_url") or ""
            img_url = _upgrade_wikipedia_image_url(img_url)
            caption = img.get("figcaption") or img.get("caption_hint") or img.get("alt") or "插图"
            img_counter += 1
            
            # 根据图片实际尺寸动态设置显示大小
            img_width = img.get("width", 0)
            img_height = img.get("height", 0)
            
            if img_width > 0:
                # 基于实际宽度设置 max-width
                if img_width >= 1200:
                    max_width = "60%"  # 大图缩小到60%
                elif img_width >= 800:
                    max_width = "55%"  # 中大图55%
                elif img_width >= 500:
                    max_width = "50%"  # 中图50%
                else:
                    max_width = "45%"  # 小图适当缩放
                _LOGGER.debug("illustrator.sizing image=%s original=%dx%d max_width=%s", img_url[:50], img_width, img_height, max_width)
            else:
                max_width = "55%"  # 没有尺寸信息时使用默认值
            
            img_html = f'''
<div align="center">
  <img src="{img_url}" alt="{caption}" style="max-width: {max_width}; height: auto;"/>
  <p><em>图 {img_counter}: {caption}</em></p>
</div>
'''
            insert_positions.append((insert_line, img_html.strip()))
        
        # 从后往前插入，避免索引偏移
        insert_positions.sort(key=lambda x: x[0], reverse=True)
        for pos, img_html in insert_positions:
            result_lines.insert(pos, "")
            result_lines.insert(pos + 1, img_html)
            result_lines.insert(pos + 2, "")
        
        return "\n".join(result_lines)
        
    except Exception as exc:
        _LOGGER.warning("illustrator_agent.llm_failed error=%s, fallback to no images", exc)
        return final_markdown


def _upgrade_wikipedia_image_url(url: str) -> str:
    """将 Wikipedia 缩略图 URL 升级为原图 URL。"""
    if not url:
        return url
    # 匹配 /thumb/.../<size>px-... 格式
    thumb_pattern = re.compile(r'/thumb/(.+?)/\d+px-[^/]+$')
    match = thumb_pattern.search(url)
    if match:
        # 移除 /thumb/ 和尺寸部分
        return re.sub(r'/thumb/(.+?)/\d+px-[^/]+$', r'/\1', url)
    return url


def assembler_agent(article_id: str, title: str, final_markdown: str) -> Dict[str, Any]:
    """Assembler：将 Markdown 落盘并返回 md_path/md_url 等信息。
    
    在此处最终清理思维内容，确保输出文件干净。
    """
    # 最终清理思维内容（之前流式传输时保留用于展示）
    cleaned_markdown = _strip_reasoning_block(final_markdown)
    
    return export_markdown(article_markdown=cleaned_markdown, title=title, article_id=article_id)


__all__ = [
    "collector_agent",
    "planner_agent",
    "researcher_agent",
    "section_writer_agent",
    "writer_audit_agent",
    "reader_review_agent",
    "doc_refiner_agent",
    "illustrator_agent",
    "assembler_agent",
]
