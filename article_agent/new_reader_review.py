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
