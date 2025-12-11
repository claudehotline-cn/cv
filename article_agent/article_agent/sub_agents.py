from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from langchain_core.messages import HumanMessage, SystemMessage

from .llm_runtime import build_chat_llm, build_structured_chat_llm, invoke_llm_with_timeout
from .schema import PlannerOutput, ResearcherOutput, SectionNotesOutput, WriterReviewOutput
from .tools_files import export_markdown, fetch_url_with_images, load_text_from_file

_LOGGER = logging.getLogger("article_agent.sub_agents")


def _split_text_into_chunks(text: str, max_chars: int = 2000, overlap: int = 200) -> List[str]:
    """将长文本按字符粗略分块，块之间保留一定重叠。

    这里只做简单分段，后续如有需要可以按句子/段落进一步优化。
    """

    if max_chars <= 0:
        return [text]

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)
        chunk = text[start:end]
        chunks.append(chunk)
        if end >= text_len:
            break
        start = max(0, end - overlap)

    return chunks


def _summarize_long_text(
    text: str,
    focus: str,
    max_chars_per_chunk: int = 2000,
    overlap: int = 200,
    timeout_sec: float = 90.0,
) -> str:
    """对长文本执行分段 + map-reduce 摘要，并结合 focus 生成聚焦摘要。"""

    if not text.strip():
        return ""

    llm = build_chat_llm(task_name="researcher_summarize")

    def _summarize_once(content: str, task_name: str) -> str:
        system_prompt = """
你是内容研究助手，负责根据给定的“研究焦点”对文本做结构化摘要。
- 只保留与研究焦点相关的重要信息；
- 用简洁的中文要点形式输出。
""".strip()
        user_prompt = f"研究焦点:\n{focus}\n\n待总结文本:\n{content}"

        def _call():
            return llm.invoke(
                [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_prompt),
                ]
            )

        result = invoke_llm_with_timeout(task_name=task_name, fn=_call, timeout_sec=timeout_sec)
        return getattr(result, "content", str(result))

    if len(text) <= max_chars_per_chunk:
        return _summarize_once(text, task_name="researcher_summarize_single")

    chunks = _split_text_into_chunks(text, max_chars=max_chars_per_chunk, overlap=overlap)
    partial_summaries: List[str] = []

    for index, chunk in enumerate(chunks):
        _LOGGER.debug("researcher.summarize_chunk index=%d length=%d", index, len(chunk))
        summary = _summarize_once(chunk, task_name=f"researcher_summarize_chunk_{index}")
        partial_summaries.append(summary)

    combined = "\n\n".join(partial_summaries)
    _LOGGER.debug("researcher.reduce_combined_length=%d", len(combined))

    # 再对所有分块摘要做一次汇总，得到最终聚焦摘要
    system_prompt = """
你是内容研究助手，负责对多段局部摘要做最终汇总。
- 结合研究焦点，去掉重复与不重要的信息；
- 输出一段结构清晰的中文摘要，可用于后续写作。
""".strip()
    user_prompt = f"研究焦点:\n{focus}\n\n各分段摘要:\n{combined}"

    def _call_reduce():
        return llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt),
            ]
        )

    result = invoke_llm_with_timeout(task_name="researcher_summarize_reduce", fn=_call_reduce, timeout_sec=timeout_sec)
    return getattr(result, "content", str(result))


def _invoke_agent(system_prompt: str, input_text: str) -> str:
    """简化版子 Agent 调用：直接使用 Chat LLM 返回字符串。"""

    llm = build_chat_llm(task_name="article")
    result = llm.invoke(
        [
            SystemMessage(content=system_prompt),
            HumanMessage(content=input_text),
        ]
    )
    return getattr(result, "content", str(result))


def _strip_markdown_fence(text: str) -> str:
    """去掉围绕全文的 ``` 代码块包裹（如 ```markdown ... ```）。"""

    if not isinstance(text, str):
        return text

    stripped = text.strip()
    if not stripped.startswith("```"):
        return text

    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[-1].strip() == "```":
        # 去掉第一行的 ```lang 与最后一行的 ```
        inner = "\n".join(lines[1:-1])
        return inner.strip("\n")
    return text


def _strip_reasoning_block(text: str) -> str:
    """去掉模型输出中的显式推理块（如 <think>...</think>）。"""

    if not isinstance(text, str):
        return text

    # 移除形如 <think> ... </think> 的思考过程，避免污染最终 Markdown 或 JSON。
    # 兼容形如 <think reason="step-by-step"> 这类带属性的标签。
    cleaned = re.sub(r"<think[^>]*>.*?</think>", "", text, flags=re.DOTALL | re.IGNORECASE)
    return cleaned.strip()


def planner_agent(
    instruction: str,
    urls: list[str],
    file_paths: list[str],
    rough_sources_overview: Any | None = None,
) -> PlannerOutput:
    system_prompt = """
你是 Planner 子 Agent，负责：
- 理解用户目标、受众与语气要求；
- 根据用户提供的链接、文件以及资料概览，规划文章的大纲 outline；
- 为每个小节给出需要研究的关键问题列表 sections_to_research。

重要约束：
- outline 必须是一个 JSON 对象（object），其每个 key 为唯一的 section_id（例如 "intro"、"langgraph" 等），
  每个 value 为该小节的定义对象（至少包含 title 或 summary 字段，用于描述该节要写什么）；
- sections_to_research 也必须是一个 JSON 对象，但它表示“需要深入研究的小节集合”：
  - 顶层 key 必须从 outline 的 section_id 列表中选择（例如 "intro"、"langgraph_overview" 等）；
  - 允许只选择其中一部分章节进行深入研究（例如可以不包含引言和结论），未出现在 sections_to_research 中的章节仍然会在后续写作阶段生成内容，但 Researcher 不会为它们额外拉取与整理资料；
  - 每个 value 为该节需要研究的问题或要点列表（可以包含 questions、notes 等字段）。

后续约束：
- Researcher 会严格以 sections_to_research 的 key 集合作为“必须生成深度笔记的小节集合”，如果缺少其中任何一节的笔记，会直接报错；
- Writer / Section Writer 会以 outline 的 section_id 集合作为最终文章结构的“主骨架”，按 outline 顺序依次写出每一节。

请使用 JSON 格式输出：
{
  "outline": {
    "<section_id>": {
      "title": "<该节标题>",
      "summary": "<该节要覆盖的核心内容说明，可选>"
    },
    ...
  },
  "sections_to_research": {
    "<section_id>": {
      "questions": ["问题1", "问题2", ...],
      "notes": "<可选的补充说明>"
    },
    ...
  }
}
""".strip()
    prompt = (
        f"用户目标: {instruction}\n"
        f"可用链接: {urls}\n"
        f"可用文件: {file_paths}\n"
        f"资料概览(rough_sources_overview): {rough_sources_overview}\n"
    )
    structured_llm = build_structured_chat_llm(PlannerOutput, task_name="planner")

    def _call():
        messages = [
            SystemMessage(content=system_prompt),
            HumanMessage(content=prompt),
        ]
        return structured_llm.invoke(messages)

    result = invoke_llm_with_timeout(
        task_name="planner",
        fn=_call,
        timeout_sec=90.0,
    )

    # 优先直接返回 Pydantic 模型实例，其次对映射/字典结果做一次 Pydantic 校验。
    if isinstance(result, PlannerOutput):
        outline_obj = result.outline
        outline_keys = (
            list(outline_obj.keys()) if isinstance(outline_obj, dict) else f"type={type(outline_obj).__name__}"
        )
        sections_keys = (
            list(result.sections_to_research.keys())
            if isinstance(result.sections_to_research, dict)
            else f"type={type(result.sections_to_research).__name__}"
        )
        _LOGGER.debug(
            "planner.structured_output keys outline=%s sections_to_research=%s",
            outline_keys,
            sections_keys,
        )
        # 同步输出到标准输出，便于在终端/容器日志中直接查看调试信息。
        print(
            f"[planner] outline_keys={outline_keys} sections_to_research_keys={sections_keys}",
            flush=True,
        )
        return result

    try:
        parsed = PlannerOutput.model_validate(result)
        outline_obj = parsed.outline
        outline_keys = (
            list(outline_obj.keys()) if isinstance(outline_obj, dict) else f"type={type(outline_obj).__name__}"
        )
        sections_keys = (
            list(parsed.sections_to_research.keys())
            if isinstance(parsed.sections_to_research, dict)
            else f"type={type(parsed.sections_to_research).__name__}"
        )
        _LOGGER.debug(
            "planner.structured_output_from_mapping keys outline=%s sections_to_research=%s",
            outline_keys,
            sections_keys,
        )
        print(
            f"[planner] (from_mapping) outline_keys={outline_keys} sections_to_research_keys={sections_keys}",
            flush=True,
        )
        return parsed
    except Exception as exc:  # pragma: no cover - 防御性
        raise RuntimeError(f"Planner 结构化输出解析失败: {exc}") from exc


def researcher_agent(
    outline: Any,
    sections_to_research: Any,
    urls: list[str],
    file_paths: list[str],
) -> ResearcherOutput:
    """Researcher 子 Agent：根据大纲对多来源原文做整理与分类。

    设计目标：
    - 不再对全文做强摘要压缩，而是按大纲/研究问题对原文进行整理与聚合；
    - 尽量保留原文段落和表达，让 Writer 在写作阶段有足够的素材可用；
    - section_notes 中的内容应包含较丰富的原文片段，而不仅仅是高度概括的要点。
    """

    # 1. 收集各来源原始文本与图片信息
    sources: List[Dict[str, Any]] = []

    for idx, url in enumerate(urls or []):
        try:
            data = fetch_url_with_images(url)
            data["id"] = f"url_{idx}"
            data["kind"] = "url"
            sources.append(data)
        except Exception as exc:  # pragma: no cover - 防御性
            _LOGGER.warning("researcher.fetch_url_failed url=%s error=%s", url, exc)

    for idx, path in enumerate(file_paths or []):
        try:
            data = load_text_from_file(path)
            data["id"] = f"file_{idx}"
            data["kind"] = "file"
            sources.append(data)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("researcher.load_file_failed path=%s error=%s", path, exc)

    source_summaries: Dict[str, Any] = {}
    image_metadata: Dict[str, Any] = {"all": []}

    focus = f"大纲: {outline}\n研究问题: {sections_to_research}"

    # 2. 对每个来源根据大纲进行整理（不强行摘要，尽量保留原文）
    for src in sources:
        text = src.get("text") or ""
        if not text.strip():
            continue

        source_id = src.get("id") or ""
        source_summaries[source_id] = {
            # 保留原文文本，供后续按小节聚合时引用
            "raw_text": text,
            "kind": src.get("kind"),
            "url": src.get("url"),
            "path": src.get("path"),
        }

        for img in src.get("images") or []:
            image_metadata.setdefault("default", []).append(
                {
                    "source_id": source_id,
                    "url": img.get("url") or img.get("src"),
                    "alt": img.get("alt", ""),
                }
            )

    # 预期的 section_id 集合：
    # - 由 sections_to_research 决定“需要深入研究的小节”，Researcher 必须为这些节生成笔记；
    # - outline 决定整篇文章最终有哪些章节（包括引言/结论等），这些章节即便没有深入研究，也会在写作阶段由 Section Writer 生成内容。
    allowed_section_ids: List[str] = []
    if isinstance(sections_to_research, dict):
        allowed_section_ids = [str(k) for k in sections_to_research.keys()]
    msg_allowed = (
        f"[researcher] allowed_section_ids={allowed_section_ids} "
        f"outline_type={type(outline).__name__} "
        f"sections_to_research_type={type(sections_to_research).__name__}"
    )
    _LOGGER.debug("researcher.allowed_section_ids %s", msg_allowed)
    print(msg_allowed, flush=True)

    # 3. 基于来源摘要与大纲生成按小节聚合的 section_notes
    section_notes: Dict[str, Any] = {}
    if source_summaries:
        base_system_prompt = """
你是 Researcher 子 Agent，负责：
- 根据文章大纲与研究问题，将各来源的原文内容按小节整理与分类；
- 每个小节的笔记中应尽量保留来自原文的关键段落和句子，可以适度删减无关内容，但不要仅给出高度概括的短摘要；
- 允许在必要时给出少量中文说明或小标题，用于组织这些原文片段；
- 你必须严格输出 JSON 对象，不能包含任何额外说明或 Markdown。
JSON 结构为：
{
  "section_notes": {
    "<section_id>": "<该节的笔记长文本>",
    ...
  }
}
""".strip()

        # 如果有明确的 section_id 集合，则在提示中显式告知，不允许新增或遗漏。
        if allowed_section_ids:
            base_system_prompt += (
                "\n\n重要约束：\n"
                f"- section_id 必须严格从以下列表中选择一个作为 key：{allowed_section_ids}；\n"
                "- 不要新增列表之外的 section_id，也不要遗漏列表中的任何一项；\n"
                "- 如果某一节没有太多可写内容，也至少给出一个简短但有信息量的笔记长文本。"
            )

        llm = build_chat_llm(task_name="researcher_section_notes")
        prompt_body = (
            f"文章大纲: {outline}\n"
            f"研究问题: {sections_to_research}\n"
            f"来源原文内容(按 source_id): {source_summaries}\n"
        )

        # 使用结构化输出（Pydantic 模型），保证 section_notes 为结构化 JSON 语义；
        structured_llm = build_structured_chat_llm(SectionNotesOutput, task_name="researcher_section_notes")

        last_error: Exception | None = None

        for attempt in range(2):
            if attempt == 0:
                system_prompt = base_system_prompt + "\n\n只输出一个 JSON 对象，不要添加任何前缀、后缀或解释。"
            else:
                system_prompt = base_system_prompt + "\n\n上一次输出不是合法 JSON，这次请仅输出符合上述结构的 JSON 对象，不要包含任何其它内容。"

            def _call():
                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=prompt_body),
                ]
                return structured_llm.invoke(messages)

            try:
                result_obj = invoke_llm_with_timeout(
                    task_name=f"researcher_section_notes_attempt_{attempt}",
                    fn=_call,
                    timeout_sec=120.0,
                )

                # 结构化路径：直接拿到 SectionNotesOutput 或通过 Pydantic 校验映射类型。
                if isinstance(result_obj, SectionNotesOutput):
                    section_notes = result_obj.section_notes
                else:
                    parsed = SectionNotesOutput.model_validate(result_obj)
                    section_notes = parsed.section_notes

                if isinstance(section_notes, dict):
                    section_keys = list(section_notes.keys())
                else:
                    section_keys = f"type={type(section_notes).__name__}"
                log_msg = f"[researcher] section_notes_keys attempt={attempt} keys={section_keys}"
                _LOGGER.debug("researcher.section_notes_keys %s", log_msg)
                print(log_msg, flush=True)
                break
            except Exception as exc:  # pragma: no cover - 防御性
                last_error = exc
                _LOGGER.warning(
                    "researcher.section_notes_structured_call_failed attempt=%d error=%s",
                    attempt,
                    exc,
                )
                continue

        # 如果两次都解析失败，则直接报错，由上游 researcher_node 统一处理。
        if not section_notes:
            msg = (
                "Researcher 无法生成任何 section_notes（多次结构化调用均失败），"
                "请检查大纲与来源内容是否合理。"
            )
            _LOGGER.error("researcher.section_notes_empty error=%s", msg)
            print(f"[researcher] ERROR {msg}", flush=True)
            raise RuntimeError(msg)

    # 若存在允许的 section_id 集合，则对 section_notes 的 key 集合做“先尝试纠正、再校验并尽量容错”的处理：
    # - 首先，如果 LLM 使用了通用的 section_1/section_2/... 命名，则按顺序尽量重命名为 allowed_section_ids（即使数量少于预期，也优先对齐前若干节）；
    # - 然后，检查 key 集合与 allowed_section_ids 的差异：仅记录 warning，不再因为“部分缺失”直接报错，以避免整个流水线因为少数节无笔记而中断。
    if allowed_section_ids and isinstance(section_notes, dict):
        expected_keys_ordered: List[str] = [str(k) for k in allowed_section_ids]
        notes_keys_ordered: List[str] = [str(k) for k in section_notes.keys()]

        # 1) 尝试处理通用的 section_1/section_2/... 命名为严格对齐的 section_id
        if 0 < len(notes_keys_ordered) <= len(expected_keys_ordered):
            # 所有 key 都形如 section_<数字> 或 sec_<数字>，视为“通用命名”，按顺序映射到 expected_keys_ordered 的前若干项。
            import re as _re

            generic_pattern = _re.compile(r"^(section|sec)_[0-9]+$", _re.IGNORECASE)
            if all(isinstance(k, str) and generic_pattern.match(k) for k in notes_keys_ordered):
                remapped: Dict[str, Any] = {}
                mapping_pairs = []
                for idx, old_key in enumerate(notes_keys_ordered):
                    if idx >= len(expected_keys_ordered):
                        break
                    new_key = expected_keys_ordered[idx]
                    remapped[new_key] = section_notes.get(old_key)
                    mapping_pairs.append((old_key, new_key))
                msg = (
                    f"[researcher] remap_section_ids generic_keys={notes_keys_ordered} "
                    f"mapping={mapping_pairs}"
                )
                _LOGGER.debug("researcher.remap_section_ids %s", msg)
                print(msg, flush=True)
                section_notes = remapped
                notes_keys_ordered = list(section_notes.keys())

        # 2) 校验 key 集合与“需要深入研究的小节集合”的关系：仅记录差异，不再中断流程
        notes_keys = {str(k) for k in section_notes.keys()}
        expected_keys = set(expected_keys_ordered)
        missing = sorted(expected_keys - notes_keys)
        extra = sorted(notes_keys - expected_keys)
        if missing or extra:
            err_msg = (
                f"[researcher] section_notes_keys_mismatch "
                f"expected={expected_keys_ordered} actual={notes_keys_ordered} "
                f"missing={missing} extra={extra}"
            )
            _LOGGER.warning("researcher.section_notes_keys_mismatch %s", err_msg)
            print(err_msg, flush=True)

        # 如果仍存在缺失的小节，则针对缺失的小节再追加一轮“补充研究”调用，尽量补齐深度笔记。
        # 仅当有来源内容且确实有缺失时才执行；若补充调用仍无法覆盖全部缺失小节，则保留已有笔记并继续流程。
        if missing and source_summaries:
            missing_ids: List[str] = [sec_id for sec_id in expected_keys_ordered if sec_id in missing]
            # 从 sections_to_research 中提取对应的小节研究问题，作为补充调用的重点。
            missing_research_spec: Dict[str, Any] = {}
            if isinstance(sections_to_research, dict):
                for sec_id in missing_ids:
                    missing_research_spec[sec_id] = sections_to_research.get(sec_id)

            _LOGGER.debug(
                "researcher.supplemental_research missing_ids=%s", missing_ids
            )
            print(
                f"[researcher] supplemental_research missing_ids={missing_ids}",
                flush=True,
            )

            supplemental_system_prompt = """
你是 Researcher 子 Agent，负责：
- 仅针对“尚未生成深度笔记”的小节，再次从已有来源中补充 section_notes；
- 每个小节的笔记中应尽量保留来自原文的关键段落和句子，可以适度删减无关内容，但不要仅给出高度概括的短摘要；
- 允许在必要时给出少量中文说明或小标题，用于组织这些原文片段；
- 你必须严格输出 JSON 对象，不能包含任何额外说明或 Markdown。
JSON 结构为：
{
  "section_notes": {
    "<section_id>": "<该节的补充笔记长文本>",
    ...
  }
}

重要约束：
- 只为以下列表中的 section_id 生成条目，不要生成其它 section_id，也不要遗漏列表中的任何一项。
""".strip()

            supplemental_system_prompt += f"\n\n需补充的小节列表: {missing_ids}"

            supplemental_prompt_body = (
                f"文章大纲: {outline}\n"
                f"需要补充笔记的小节及其研究问题: {missing_research_spec}\n"
                f"来源原文内容(按 source_id): {source_summaries}\n"
            )

            supplemental_llm = build_structured_chat_llm(
                SectionNotesOutput,
                task_name="researcher_section_notes_missing",
            )

            supplemental_last_error: Exception | None = None

            for attempt in range(2):
                if attempt == 0:
                    supplemental_sp = (
                        supplemental_system_prompt
                        + "\n\n只输出一个 JSON 对象，不要添加任何前缀、后缀或解释。"
                    )
                else:
                    supplemental_sp = (
                        supplemental_system_prompt
                        + "\n\n上一次输出不是合法 JSON，这次请仅输出符合上述结构的 JSON 对象，不要包含任何其它内容。"
                    )

                def _call_supplemental():
                    messages = [
                        SystemMessage(content=supplemental_sp),
                        HumanMessage(content=supplemental_prompt_body),
                    ]
                    return supplemental_llm.invoke(messages)

                try:
                    supplemental_obj = invoke_llm_with_timeout(
                        task_name=f"researcher_section_notes_missing_attempt_{attempt}",
                        fn=_call_supplemental,
                        timeout_sec=120.0,
                    )

                    if isinstance(supplemental_obj, SectionNotesOutput):
                        supplemental_notes = supplemental_obj.section_notes
                    else:
                        parsed_sup = SectionNotesOutput.model_validate(supplemental_obj)
                        supplemental_notes = parsed_sup.section_notes

                    if not isinstance(supplemental_notes, dict) or not supplemental_notes:
                        continue

                    # 仅合并缺失小节中实际有内容的笔记。
                    merged_count = 0
                    for sec_id in missing_ids:
                        note = supplemental_notes.get(sec_id)
                        if isinstance(note, str) and note.strip():
                            section_notes[sec_id] = note
                            merged_count += 1

                    _LOGGER.debug(
                        "researcher.supplemental_research_merged count=%d", merged_count
                    )
                    print(
                        f"[researcher] supplemental_research_merged ids={missing_ids} merged_count={merged_count}",
                        flush=True,
                    )
                    break
                except Exception as exc:  # pragma: no cover - 防御性
                    supplemental_last_error = exc
                    _LOGGER.warning(
                        "researcher.supplemental_research_failed attempt=%d error=%s",
                        attempt,
                        exc,
                    )
                    continue

    # 4. 对 section_notes 做简单的跨节与小结标注，辅助后续 Section Writer / Refiner。
    if isinstance(section_notes, dict) and section_notes:
        # 4.1 标记“【跨节共用】”：如果完全相同的笔记文本出现在多个 section_id 中。
        text_to_sections: Dict[str, List[str]] = {}
        for sec_id, note in section_notes.items():
            if isinstance(note, str):
                key = note.strip()
                if key:
                    text_to_sections.setdefault(key, []).append(str(sec_id))

        for key, sec_ids in text_to_sections.items():
            if len(sec_ids) <= 1:
                continue
            for sec_id in sec_ids:
                value = section_notes.get(sec_id)
                if isinstance(value, str) and "【跨节共用】" not in value:
                    section_notes[sec_id] = f"【跨节共用】\n{value}"

        # 4.2 标记“小结缺失”：若某个 section 的笔记中不包含“小结”字样，提醒 Writer 在该节末尾补充小结。
        for sec_id, note in list(section_notes.items()):
            if not isinstance(note, str):
                continue
            if "小结" in note or "【小结缺失】" in note:
                continue
            section_notes[sec_id] = note + "\n\n【小结缺失】请在本小节输出时补充 2-3 句小结。"

    return ResearcherOutput(
        source_summaries=source_summaries,
        section_notes=section_notes,
        image_metadata=image_metadata,
    )


def collector_agent(
    instruction: str,
    urls: list[str],
    file_paths: list[str],
    max_text_chars: int = 4000,
) -> List[Dict[str, Any]]:
    """轻量 Researcher / Collector：

    - 快速拉取每个来源的标题与粗略摘要；
    - 不做细粒度分节，仅用于 Planner 阶段了解资料全貌。
    """

    sources: List[Dict[str, Any]] = []

    # URL 源概览
    for idx, url in enumerate(urls or []):
        try:
            data = fetch_url_with_images(url)
            text: str = data.get("text") or ""
            if len(text) > max_text_chars:
                text = text[:max_text_chars]
            overview = {
                "id": f"url_{idx}",
                "kind": "url",
                "url": url,
                "title": data.get("title", ""),
                "rough_snippet": text,
                "num_images": len(data.get("images") or []),
            }
            sources.append(overview)
        except Exception as exc:  # pragma: no cover - 防御性
            _LOGGER.warning("collector.fetch_url_failed url=%s error=%s", url, exc)

    # 文件源概览
    for idx, path in enumerate(file_paths or []):
        try:
            info = load_text_from_file(path, max_text_chars=max_text_chars)
            text: str = info.get("text") or ""
            if len(text) > max_text_chars:
                text = text[:max_text_chars]
            overview = {
                "id": f"file_{idx}",
                "kind": "file",
                "path": info.get("path", path),
                "title": info.get("path", path),
                "rough_snippet": text,
                "num_images": len(info.get("images") or []),
            }
            sources.append(overview)
        except Exception as exc:  # pragma: no cover
            _LOGGER.warning("collector.load_file_failed path=%s error=%s", path, exc)

    _LOGGER.debug("collector.sources_count=%d instruction=%s", len(sources), instruction[:80])
    return sources


def writer_agent(instruction: Any, outline: Any, section_notes: Any, image_metadata: Any) -> str:
    system_prompt = """
你是 Writer 子 Agent，负责：
- 根据 outline 和 section_notes 写出结构清晰、内容尽量充实的 Markdown 文章草稿；
- 字数、风格和内容重点以用户的 instruction 为准；
- 在合适位置预留插图位置。

- 用户的原始 instruction 如下，请尽量严格遵守其中对字数、风格、读者与重点的要求：
- {{instruction}}

写作要求：
- 如果 instruction 中对字数有明确要求（例如“不少于 2000 字”或“尽量简短”），请严格遵守；若未指定，则根据资料量和主题合理控制篇幅；
- 如果 instruction 中对读者类型或语气有要求（例如“面向产品经理，少代码”），请优先满足，不要用你自己的默认偏好覆盖用户要求；
- 充分利用 section_notes 中的要点进行“重写和组织”，而不是复制原文或简单拼接原始资料；
- 在不违背 instruction 的前提下，可适当结合工程实践经验、踩坑点或注意事项，帮助目标读者更好理解主题。

- 直接输出 Markdown 正文本身，不要用 ```markdown``` 或 ``` 包裹整篇文章。
- 不要输出你的思考过程、推理步骤或以 <think>...</think> 形式出现的内容，仅输出面向读者的文章正文。

输出内容为完整 Markdown 字符串。
""".strip()
    prompt = (
        f"用户 instruction: {instruction}\n"
        f"大纲: {outline}\n"
        f"每节要点: {section_notes}\n"
        f"图片信息: {image_metadata}\n"
    )
    raw = _invoke_agent(system_prompt, prompt)
    cleaned = _strip_markdown_fence(raw)
    cleaned = _strip_reasoning_block(cleaned)
    _LOGGER.debug("writer.raw_output_length=%d", len(cleaned) if isinstance(cleaned, str) else -1)
    return cleaned


def section_writer_agent(
    instruction: Any,
    outline: Any,
    section_notes: Dict[str, Any],
    timeout_sec: float = 180.0,
) -> Dict[str, str]:
    """Section Writer：按小节逐段生成 Markdown 片段。

    - 输入：整体 instruction、outline 与按 section_id 划分的 section_notes；
    - 输出：section_drafts 映射，每个 section_id 对应一段 Markdown 小节正文；
    - 设计目标：缩小单次写作任务空间，让模型专注写好当前小节。
    """

    llm = build_chat_llm(task_name="section_writer")
    drafts: Dict[str, str] = {}

    if not isinstance(section_notes, dict):
        section_notes = {}

    # 优先按照 outline 中的章节顺序写作，保证最终文章结构与 Planner 大纲完全一致；
    # 若无法解析 outline，则退回到对 section_notes 中已有 key 的遍历顺序。
    ordered_section_ids: List[str] = []
    if isinstance(outline, dict):
        ordered_section_ids = [str(k) for k in outline.keys()]
    else:
        ordered_section_ids = [str(k) for k in section_notes.keys()]

    for section_id in ordered_section_ids:
        # 对于没有深入研究笔记的章节（不在 section_notes 中），notes 设为空字符串，
        # 由模型基于 instruction + outline 中该节的定义来生成概览/引言/结论等内容。
        notes = section_notes.get(section_id, "")

        # 尝试从 outline 中取出当前小节的定义，帮助 Writer 聚焦本节内容。
        section_outline = None
        if isinstance(outline, dict) and section_id in outline:
            section_outline = outline.get(section_id)

        system_prompt = """
你是 Section Writer，只负责写“某一节”的内容。

- 输入包括：
  - 整体写作目标与读者信息（instruction 摘要）；
  - 全文大纲 outline（仅供参考，不必重复其它小节的内容）；
  - 当前小节的 section_notes：这是 Researcher 为该小节整理好的“素材池”，包含原文片段和研究备注。

你的职责：
- 只写本小节的正文内容，不负责整篇文章；
- 尽量利用 section_notes 中的要点进行重写和组织，而不是简单复制原文；
- 通过合适的导语、过渡句和小结，让本小节在整篇文章中逻辑顺畅。

输出要求：
- 输出一段 Markdown 片段：
  - 第一行必须是本小节的主标题，使用二级标题形式：以 `## ` 开头，标题内容优先使用大纲中该节的 title（若 outline[section_id] 中包含 title 字段），否则可结合 section_id 与整体 instruction 自行拟定；
  - 如需在本节内部进一步分节，请仅使用三级或更低级标题（例如 `###`、`####`），不要再创建新的二级标题，以免破坏整篇文章按大纲划分的主结构；
  - 包含导语、正文与小结；
  - 不包含整篇文章的一级标题（`#`），只写本节内容。
- 使用中文，面向有工程经验的读者，偏工程实践、少空话。
 - 篇幅要求：除非 instruction 中有更严格的字数限制，每个重要小节的正文不少于约 500 字；如 section_notes 中标注了“【跨节共用】”或说明为核心/重点小节，可写到 800～1200 字。
 - 小结要求：本小节结束前必须添加一段以 `**小结：**` 开头的段落，用 2～3 句话总结本节对整篇文章的关键收获。

禁止事项：
- 不要在输出中解释你是如何思考的，也不要出现“我先来分析一下”“现在我将...”这类自述；
- 不要输出你的思考过程、推理步骤或以 <think>...</think> 形式出现的内容；
- 不要写本节以外的内容。
""".strip()

        prompt = (
            f"整体 instruction: {instruction}\n"
            f"全文大纲 outline: {outline}\n"
            f"当前小节在大纲中的定义(若有): {section_outline}\n"
            f"当前 section_id: {section_id}\n"
            f"当前小节的 section_notes:\n{notes}\n"
        )

        def _call():
            return llm.invoke(
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
        raw = getattr(result, "content", str(result))
        cleaned = _strip_markdown_fence(raw)
        cleaned = _strip_reasoning_block(cleaned)
        # 记录当前小节的首行标题，便于排查标题与 outline 不一致的问题。
        first_line = ""
        if isinstance(cleaned, str):
            first_line = cleaned.splitlines()[0].strip() if cleaned.splitlines() else ""
        outline_title = (
            section_outline.get("title") if isinstance(section_outline, dict) else None
        )
        log_msg = (
            f"[section_writer] section_id={section_id} "
            f"outline_title={outline_title} first_line={first_line}"
        )
        _LOGGER.debug("section_writer.output %s", log_msg)
        print(log_msg, flush=True)
        drafts[str(section_id)] = cleaned

    return drafts


def doc_refiner_agent(instruction: Any, draft_markdown: str, timeout_sec: float = 240.0) -> str:
    """Doc Refiner：对整篇草稿进行一次通篇重写与质量提升。

    - 目标：统一风格、去重、增强衔接，在不丢失关键信息的前提下整体提升可读性。
    """

    if not draft_markdown:
        return draft_markdown

    llm = build_chat_llm(task_name="doc_refiner")
    system_prompt = """
你是 Doc Refiner，负责在现有完整草稿的基础上，对整篇文章进行“通篇重写与质量提升”。

你会收到：
- 写作目标与读者信息（instruction 摘要）；
- 合并后的完整草稿 draft_markdown（由各小节拼接而成）。

你的任务：
1. 在不改变主要事实和整体结构的前提下，对全文进行整体优化：
   - 统一语气、风格和人称；
   - 删除跨章节的重复段落或意思完全相同的句子；
   - 补充必要的衔接段和总结句，让各章节之间逻辑更流畅；
   - 保留关键细节和工程实践内容，不要过度压缩。
2. 保持大纲层级不变，仍然使用 Markdown 标题层级结构。

篇幅要求：
- 总体字数可以有适度压缩或扩展，但应大致保持在原稿字数的 80%～120% 之间；
- 不允许无意义地砍到原来的一半以下，使内容严重缩水。

小结要求：
- 检查各二级/三级标题小节是否已经包含以“**小结：**”开头的总结段落；
- 对于缺少小结但在大纲中属于重要章节的小节，请在该小节末尾补充一个 2～3 句的小结段，用 `**小结：**` 开头，概括本节对全文的贡献。

输出要求：
- 直接输出重写后的完整 Markdown 文本；
- 不输出任何额外说明、点评或自述过程；
- 不包含 ```markdown 或 ``` 代码块包裹全文；
- 不要输出你的思考过程、推理步骤或以 <think>...</think> 形式出现的内容。
""".strip()

    prompt = (
        f"整体 instruction: {instruction}\n"
        f"当前完整草稿 draft_markdown:\n{draft_markdown}\n"
    )

    def _call():
        return llm.invoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt),
            ]
        )

    result = invoke_llm_with_timeout(
        task_name="doc_refiner",
        fn=_call,
        timeout_sec=timeout_sec,
    )
    raw = getattr(result, "content", str(result))
    cleaned = _strip_markdown_fence(raw)
    cleaned = _strip_reasoning_block(cleaned)

    # 结构保护：若 Refiner 破坏了按 outline 划分的二级标题结构，则回退到原始草稿；
    # 否则在保持二级标题文本与顺序不变的前提下，仅接受正文内容的改写。
    if not isinstance(cleaned, str):
        return cleaned

    original_text = draft_markdown or ""
    original_lines = original_text.splitlines()
    new_lines = cleaned.splitlines()

    # 仅关注以 "## " 开头的二级标题，视为按 outline 划分的小节边界。
    original_headings = [line for line in original_lines if line.lstrip().startswith("## ")]
    new_heading_indices = [idx for idx, line in enumerate(new_lines) if line.lstrip().startswith("## ")]

    if original_headings:
        if len(new_heading_indices) != len(original_headings):
            msg = (
                f"[doc_refiner] heading_count_mismatch "
                f"original={len(original_headings)} refined={len(new_heading_indices)}，"
                f"回退使用未精修草稿。"
            )
            _LOGGER.warning("doc_refiner.heading_count_mismatch %s", msg)
            print(msg, flush=True)
            return original_text

        # 覆写 Refiner 生成的二级标题文本，保持与原稿完全一致，仅保留其对段落内容的改写。
        heading_idx = 0
        for line_idx in new_heading_indices:
            if heading_idx >= len(original_headings):
                break
            indent = new_lines[line_idx][: len(new_lines[line_idx]) - len(new_lines[line_idx].lstrip())]
            new_lines[line_idx] = indent + original_headings[heading_idx].lstrip()
            heading_idx += 1

        cleaned = "\n".join(new_lines)

    return cleaned


def writer_review_agent(outline: Any, section_notes: Any, draft_markdown: str) -> WriterReviewOutput:
    """Writer 自检 Agent：评估草稿质量并决定是否需要重写。"""

    base_system_prompt = """
你是 Writer 自检助手，负责：
- 根据文章大纲与小节笔记，检查当前 Markdown 草稿的结构与内容质量；
- 判断是否“需要重写”(needs_revision)；
- 说明需要改进的要点（comments）。

你必须严格输出 JSON 对象，不能包含任何额外说明或 Markdown。
JSON 结构为：
{
  "needs_revision": true/false,
  "comments": "..."
}
""".strip()

    llm = build_chat_llm(task_name="writer_review")
    prompt_body = (
        f"文章大纲: {outline}\n"
        f"小节笔记: {section_notes}\n"
        f"当前 Markdown 草稿:\n{draft_markdown}\n"
    )

    # 使用结构化输出（with_structured_output + Pydantic），保证输出为 JSON 语义；
    structured_llm = build_structured_chat_llm(WriterReviewOutput, task_name="writer_review")

    last_error: Exception | None = None

    for attempt in range(2):
        if attempt == 0:
            system_prompt = base_system_prompt + "\n\n只输出一个 JSON 对象，不要添加任何前缀、后缀或解释。"
        else:
            system_prompt = base_system_prompt + "\n\n上一次输出不是合法 JSON，这次请仅输出符合上述结构的 JSON 对象，不要包含任何其它内容。"

        def _call():
            messages = [
                SystemMessage(content=system_prompt),
                HumanMessage(content=prompt_body),
            ]
            return structured_llm.invoke(messages)

        try:
            result = invoke_llm_with_timeout(
                task_name=f"writer_review_attempt_{attempt}",
                fn=_call,
                timeout_sec=90.0,
            )

            # 结构化路径：直接返回 WriterReviewOutput 或通过 Pydantic 校验映射类型。
            if isinstance(result, WriterReviewOutput):
                return result

            parsed = WriterReviewOutput.model_validate(result)
            return parsed
        except Exception as exc:  # pragma: no cover - 防御性
            last_error = exc
            _LOGGER.warning("writer_review.structured_output_failed attempt=%d error=%s", attempt, exc)
            continue

    # 多次尝试仍失败：视为“不需要重写”，并将最后一次错误信息写入 comments，方便排查。
    return WriterReviewOutput(
        needs_revision=False,
        comments=str(last_error) if last_error is not None else "",
    )


def illustrator_agent(draft_markdown: str, image_metadata: Any) -> str:
    system_prompt = """
你是 Illustrator(图片策展) 子 Agent，负责：
- 只使用已有 image_metadata 中的图片信息；
- 在 Markdown 中插入 `![说明](图片路径或URL)`；
- 不生成新图片，也不虚构图片路径。
输出内容为“在原有 Markdown 草稿基础上，仅插入图片后的完整 Markdown 字符串”。

严格约束：
- 你必须以输入的“Markdown 草稿”为基础，只在合适位置插入或替换图片引用行；
- 除了插入/替换图片行之外，不得删除、改写或重排任何原有内容；
- 不要只返回某几个小节或片段，最终输出必须覆盖原草稿的全部章节与段落。

请直接输出 Markdown 正文，不要额外包裹 ```markdown``` 或 ``` 代码块。
不要输出你的思考过程、推理步骤或以 <think>...</think> 形式出现的内容，仅输出最终的文章 Markdown。
""".strip()
    prompt = f"Markdown 草稿: {draft_markdown}\n图片信息: {image_metadata}\n"
    raw = _invoke_agent(system_prompt, prompt)
    _LOGGER.debug(
        "illustrator.raw_output_length=%d",
        len(raw) if isinstance(raw, str) else -1,
    )

    # 清理可能出现的 Markdown 代码块包裹与推理内容（如 <think>...</think>），并丢弃前置的“自述型”说明段落。
    cleaned = _strip_markdown_fence(raw)
    cleaned = _strip_reasoning_block(cleaned)

    if isinstance(cleaned, str):
        # 若模型仍输出了大量“我现在来处理/先分析一下”等前言，
        # 则保留从第一个 Markdown 标题开始的内容（支持 # / ## / ### 等各级标题）。
        lines = cleaned.splitlines()
        first_heading_idx: int | None = None
        heading_pattern = re.compile(r"^\s*#{1,6}\s+")
        for idx, line in enumerate(lines):
            if heading_pattern.match(line):
                first_heading_idx = idx
                break
        if first_heading_idx is not None and first_heading_idx > 0:
            cleaned = "\n".join(lines[first_heading_idx:])

    _LOGGER.debug(
        "illustrator.cleaned_output_length=%d",
        len(cleaned) if isinstance(cleaned, str) else -1,
    )
    return cleaned


def assembler_agent(article_id: str, title: str, final_markdown: str) -> Dict[str, Any]:
    """Assembler 负责调用 export_markdown 保存文件并返回下载链接。"""

    info = export_markdown(article_markdown=final_markdown, title=title, article_id=article_id)
    return {"output": info}


__all__ = [
    "collector_agent",
    "planner_agent",
    "researcher_agent",
    "writer_agent",
    "writer_review_agent",
    "illustrator_agent",
    "assembler_agent",
]
