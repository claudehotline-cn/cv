from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from langchain.agents import create_agent
from langchain_core.tools import tool

from .graph import get_content_graph
from ..config.llm_runtime import build_chat_llm

_LOGGER = logging.getLogger("article_agent.chat_graph")


CHAT_AGENT_SYSTEM_PROMPT = """
你是一个“内容整理入口” Agent，负责根据用户提供的说明、网页链接和文件路径，调用一个高阶工具 generate_article 来运行完整的文章生成流水线。

【总体目标】
- 面向用户指定的读者和语气要求，生成一篇结构清晰、内容贴合需求的 Markdown 文章；
- 在合适位置插入来自原始资料的图片引用；
- 最终通过导出工具生成可下载的 Markdown 文件，并将下载链接返回给用户。

【可用工具】
1. generate_article
   - 输入：
     - instruction: 用户对文章的整体要求（主题、读者、语气、字数等），请直接使用用户提供的中文描述。
     - urls: 需要整理的网页链接列表，从用户消息中提取所有 http(s) 开头的 URL。
     - file_paths: 需要整理的本地文件路径列表（如有）。
     - article_id: 文章 ID，如用户未指定，可使用简单 ID（例如 "article-001"）。
     - title: 可选的文章标题，如用户未指定，可留空，由内部流程推断。
   - 作用：
     - 固定按如下顺序执行内部子流程：init → collector → planner → researcher → research_audit → section_writer → writer_audit → merge_sections → doc_refiner(可选) → illustrator → assembler → summary_for_user；
     - 返回 JSON，包含 article_id、title、md_url、md_path、step_history、summary_for_user 和 error 等字段。

【调用策略】
- 当用户提出“基于若干链接/文件生成文章/博客/技术文档”之类需求时：
  - 不要自己一步到位写长文；
  - 应至少调用一次 generate_article 工具完成完整流水线；
  - 不要只做规划或大纲就结束本轮回答。

【和用户对话时的行为】
- 尽量一次性收集清楚：目标读者、字数要求、语气偏好、文章主题；
- 一旦信息足够，请调用 generate_article，将用户原始 instruction 与所有 urls/file_paths 一并传入；
- 在 generate_article 返回结果后，用中文总结：
  - 文章标题；
  - 各主要部分的内容结构；
  - Markdown 下载链接（md_url）；
- 不要绕过 generate_article 自己去抓取网页或直接写长文，所有实际生成流程应在 generate_article 内部完成。
""".strip()


@tool("generate_article")
def generate_article_tool(
    instruction: str,
    urls: Optional[List[str]] = None,
    file_paths: Optional[List[str]] = None,
    article_id: Optional[str] = None,
    title: Optional[str] = None,
) -> str:
    """根据 instruction + urls + file_paths 运行完整内容整理流水线，并返回 Markdown 下载链接等信息（JSON 字符串）。

    - 请将用户原始指令完整传入 instruction；
    - urls 填写用户消息中出现的所有 http(s) 链接；
    - file_paths 填写用户提供的本地文件路径（如有）；
    - 如用户未指定 article_id，可以使用类似 "article-001" 的简短 ID。
    """

    urls = urls or []
    file_paths = file_paths or []
    article_id = article_id or "article-auto"

    _LOGGER.info(
        "generate_article_tool.start instruction=%s urls=%s file_paths=%s article_id=%s",
        instruction[:120],
        urls,
        file_paths,
        article_id,
    )

    graph = get_content_graph()
    state = graph.invoke(
        {
            "instruction": instruction,
            "urls": urls,
            "file_paths": file_paths,
            "article_id": article_id,
            "title": title or "",
        }
    )

    final_title = (state.get("title") or title or "未命名文章").strip() or "未命名文章"
    result: Dict[str, Any] = {
        "article_id": state.get("article_id") or article_id,
        "title": final_title,
        "md_url": state.get("md_url"),
        "md_path": state.get("md_path"),
        "step_history": state.get("step_history", []),
        "error": state.get("error"),
        "summary_for_user": state.get("summary_for_user"),
    }

    _LOGGER.info(
        "generate_article_tool.done article_id=%s md_url=%s error=%s",
        result["article_id"],
        result["md_url"],
        result["error"],
    )
    return json.dumps(result, ensure_ascii=False)


def get_content_chat_agent_graph() -> Any:
    """构造一个面向 Agent Chat UI 的 Graph。

    - 状态：messages 形式，由 LangChain create_agent 提供；
    - 工具：暴露 generate_article 工具，内部调用内容整理 StateGraph；
    - 用途：通过自然语言对话触发完整文章生成流水线，并在工具结果中返回 Markdown 下载链接。
    """

    model = build_chat_llm(task_name="content_chat_agent")
    tools: List[Any] = [generate_article_tool]

    agent = create_agent(
        model=model,
        tools=tools,
        system_prompt=CHAT_AGENT_SYSTEM_PROMPT,
    )
    return agent.with_config({"recursion_limit": 100})


__all__ = ["get_content_chat_agent_graph"]
