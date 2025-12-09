from __future__ import annotations

from typing import Any, Dict, List, TypedDict
import logging

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage
from langgraph.graph import StateGraph, START, END

from .db.schema import DbAnalysisRequest, DbAgentResponse
from .db.graph import invoke_db_chart_agent

_LOGGER = logging.getLogger("agent_langchain.db_chat")


class DbChatState(TypedDict, total=False):
    """Agent Chat UI 期望的标准状态结构：至少包含 messages。"""

    messages: List[BaseMessage]  # 实际运行时也可能是 dict 形式的消息
    response: DbAgentResponse


def _extract_last_user_message_content(messages: List[Any]) -> str | None:
    """从 messages 列表中提取最后一条用户消息的文本内容。

    同时兼容：
    - LangChain BaseMessage（HumanMessage 等）对象；
    - dict 形式：{"role": "user"|"human", "content": "..."}。
    """

    for m in reversed(messages):
        # dict 形式
        if isinstance(m, dict):
            role = (m.get("role") or m.get("type") or "").lower()
            if role in ("human", "user"):
                content = m.get("content")
                # 1) 纯字符串内容
                if isinstance(content, str) and content.strip():
                    return content.strip()
                # 2) LangGraph/Agent Chat UI 富文本结构：
                #    [{"type": "text", "text": "..."}]
                if isinstance(content, list):
                    parts: List[str] = []
                    for item in content:
                        if not isinstance(item, dict):
                            continue
                        if (item.get("type") or "").lower() == "text":
                            text = item.get("text")
                            if isinstance(text, str) and text.strip():
                                parts.append(text.strip())
                    if parts:
                        return " ".join(parts)
                # 3) 其它结构暂不处理
                continue

        # BaseMessage 形式
        if isinstance(m, HumanMessage) or getattr(m, "type", None) == "human":
            text = getattr(m, "content", "") or ""
            if isinstance(text, str) and text.strip():
                return text.strip()

    return None


def _build_db_chat_graph() -> Any:
    """构建一个简单的“聊天 → DB 图表分析” Graph。

    - 输入状态：{"messages": [...]}，其中最后一条 user 消息的 content 作为数据库分析 query；
    - 使用现有的 invoke_db_chart_agent 执行 DB 分析；
    - 将分析结论或简要提示以 AIMessage 形式追加到 messages 中，供 Agent Chat UI 展示。
    """

    graph = StateGraph(DbChatState)

    def call_db_node(state: DbChatState) -> DbChatState:
        msgs = state.get("messages") or []
        if not msgs:
            # 初始空对话：不抛错，返回一条提示消息
            _LOGGER.info("db_chat.call_db_node.empty_messages")
            hint = AIMessage(content="请先在聊天框中输入你想查询的数据库问题，例如：“按月份统计订单金额和订单数”。")
            state["messages"] = [hint]  # type: ignore[list-item]
            return state

        query_text = _extract_last_user_message_content(msgs)
        if not query_text:
            # 找不到用户消息时，不抛错，提示用户重新输入
            _LOGGER.warning("db_chat.call_db_node.no_user_message messages=%s", msgs)
            reply = AIMessage(content="暂时没有找到可用的用户问题，请重新输入你想分析的数据库问题。")
            new_messages: List[BaseMessage] = list(msgs) + [reply]  # type: ignore[list-item]
            state["messages"] = new_messages
            return state

        _LOGGER.info("db_chat.call_db_node query=%s", query_text)

        # 简单使用固定 session_id；后续如需按线程区分，可结合 config 进行扩展。
        request = DbAnalysisRequest(session_id="agent-chat-ui", query=query_text, db_name=None)
        response = invoke_db_chart_agent(request=request)

        # 构造简要回复：优先使用 insight，其次提示图表数量
        if response.insight:
            reply_text = response.insight
        else:
            charts_cnt = len(response.charts or [])
            if charts_cnt > 0:
                reply_text = f"已根据你的问题生成了 {charts_cnt} 个图表，可以在图表视图中查看详细可视化结果。"
            else:
                reply_text = "未能生成任何图表，请尝试用更具体的方式描述你想查看的数据库统计。"

        # 将图表结果编码到 AIMessage 的富文本内容中，供 Agent Chat UI 解析并渲染。
        charts_payload: List[Dict[str, Any]] = []
        for c in response.charts or []:
            try:
                option = getattr(c, "option", None) or {}
                dataset = option.get("dataset", {})
                # dataset 可能是 dict 或 list，统一取第一个 source
                dataset_source = None
                if isinstance(dataset, dict):
                    dataset_source = dataset.get("source")
                elif isinstance(dataset, list) and dataset:
                    first_ds = dataset[0] or {}
                    if isinstance(first_ds, dict):
                        dataset_source = first_ds.get("source")

                # 尝试从 ECharts dataset transform 中推断系列维度（series_dimension）
                series_dimension: str | None = None
                if isinstance(dataset, list) and len(dataset) > 1:
                    for ds in dataset[1:]:
                        if not isinstance(ds, dict):
                            continue
                        transform = ds.get("transform") or {}
                        if not isinstance(transform, dict):
                            continue
                        cfg = transform.get("config") or {}
                        if not isinstance(cfg, dict):
                            continue
                        dim = cfg.get("dimension")
                        if isinstance(dim, str) and dim:
                            series_dimension = dim
                            break

                charts_payload.append(
                    {
                        "id": c.id,
                        "title": c.title,
                        "description": c.description,
                        "option": option,
                        "dataset_source": dataset_source,
                        "series_dimension": series_dimension,
                    }
                )
            except Exception as exc:  # pragma: no cover - 防御性
                _LOGGER.warning("db_chat.serialize_chart_failed id=%s error=%s", getattr(c, "id", None), exc)
                continue

        content_parts: List[Dict[str, Any]] = [
            {"type": "text", "text": reply_text},
        ]
        if charts_payload:
            content_parts.append(
                {
                    "type": "json",
                    "json": {
                        "__cv_charts": charts_payload,
                    },
                }
            )

        ai_msg = AIMessage(content=content_parts)
        new_messages = list(msgs) + [ai_msg]  # type: ignore[list-item]

        state["messages"] = new_messages
        state["response"] = response
        return state

    graph.add_node("call_db", call_db_node)
    graph.add_edge(START, "call_db")
    graph.add_edge("call_db", END)

    return graph.compile()


def get_db_chat_graph() -> Any:
    """供 langgraph.json 引用的入口。"""

    return _build_db_chat_graph()
