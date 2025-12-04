import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from pydantic import BaseModel, Field

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_ollama import ChatOllama
from langgraph.errors import GraphRecursionError

from ..config import get_settings
from ..graph import (
    AgentState,
    build_state_from_tuples,
    get_control_plane_agent,
    get_stategraph_agent,
)
from ..excel.graph import invoke_excel_chart_agent
from ..excel.schema import ExcelAnalysisRequest, ExcelAgentResponse
from ..db.graph import invoke_db_chart_agent
from ..db.schema import DbAnalysisRequest, DbAgentResponse
from ..store.thread_summary import (
    get_agent_stats,
    get_thread_summary,
    list_thread_summaries,
    update_summary_for_control,
    update_summary_for_messages,
)
from ..tools.pipelines import (
    _fetch_pipelines,
)
from ..tools import (
    delete_pipeline_tool,
    drain_pipeline_tool,
    hotswap_model_tool,
    plan_delete_pipeline_tool,
    plan_drain_pipeline_tool,
    plan_hotswap_model_tool,
)

logger = logging.getLogger("cv_agent")

try:
    # 可选依赖：若未安装 prometheus_client，则不暴露 /metrics 端点，也不记录 HTTP 指标。
    from prometheus_client import Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest  # type: ignore[import]
except Exception:  # pragma: no cover - 可选依赖
    Counter = Histogram = None  # type: ignore[assignment]
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4; charset=utf-8"
    generate_latest = None  # type: ignore[assignment]


if Counter is not None and Histogram is not None:  # pragma: no cover - 依赖存在时才注册
    _HTTP_REQUEST_COUNTER = Counter(
        "cv_agent_http_requests_total",
        "Total HTTP requests handled by cv_agent, labeled by path and method",
        ["path", "method"],
    )
    _HTTP_REQUEST_LATENCY = Histogram(
        "cv_agent_http_request_duration_seconds",
        "HTTP request latency observed by cv_agent (seconds)",
        ["path", "method"],
    )
else:  # pragma: no cover - 未安装 prometheus_client
    _HTTP_REQUEST_COUNTER = None
    _HTTP_REQUEST_LATENCY = None


def _record_http_metrics(path: str, method: str, duration_ms: float) -> None:
    """将 HTTP 请求的基本指标写入 Prometheus（如已启用）。"""

    if _HTTP_REQUEST_COUNTER is not None:
        _HTTP_REQUEST_COUNTER.labels(path=path, method=method).inc()
    if _HTTP_REQUEST_LATENCY is not None and duration_ms >= 0.0:
        _HTTP_REQUEST_LATENCY.labels(path=path, method=method).observe(
            float(duration_ms) / 1000.0
        )


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_configure_logging()

app = FastAPI(title="CV Agent Service", version="0.1.0")


if generate_latest is not None:  # pragma: no cover - 仅在安装 prometheus_client 时启用

    @app.get("/metrics")
    async def metrics() -> Response:
        """Prometheus 指标导出端点。"""

        data = generate_latest()
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)


class Message(BaseModel):
    role: Literal["user", "assistant", "system", "tool"] = Field(
        description="消息角色（user/assistant/system/tool）"
    )
    content: str = Field(description="消息内容")


class ControlParams(BaseModel):
    pipeline_name: Optional[str] = Field(
        default=None,
        description="目标 pipeline 名称",
    )
    node: Optional[str] = Field(
        default=None,
        description="hotswap 使用的节点名称",
    )
    model_uri: Optional[str] = Field(
        default=None,
        description="hotswap 使用的新模型 URI",
    )
    timeout_sec: Optional[int] = Field(
        default=None,
        ge=0,
        description="drain 使用的超时时间（秒），缺省则使用后端默认值",
    )


class ControlRequest(BaseModel):
    op: Literal["pipeline.delete", "pipeline.hotswap", "pipeline.drain"] = Field(
        description="控制操作类型"
    )
    mode: Literal["plan", "execute"] = Field(
        description="控制操作模式：plan 或 execute"
    )
    params: ControlParams = Field(description="控制操作参数")
    confirm: bool = Field(
        default=False,
        description="仅在 mode=execute 且 confirm=true 时允许执行高危操作",
    )


class ControlResult(BaseModel):
    op: str = Field(description="控制操作类型")
    mode: Literal["plan", "execute"] = Field(description="控制操作模式")
    success: bool = Field(description="控制操作是否成功")
    plan: Optional[Dict[str, Any]] = Field(
        default=None, description="plan_* 工具返回的规划结果"
    )
    result: Optional[Dict[str, Any]] = Field(
        default=None, description="执行工具返回的结果（execute 模式下）"
    )
    plan_steps: Optional[List[Dict[str, Any]]] = Field(
        default=None,
        description="计划步骤列表，通常基于 plan_* 工具返回值抽象。",
    )
    execute_result: Optional[Dict[str, Any]] = Field(
        default=None,
        description="执行阶段聚合结果（成功/失败/错误信息等），便于前端直接展示。",
    )
    error: Optional[str] = Field(
        default=None, description="失败时的错误信息（如果有）"
    )


class AgentInvokeRequest(BaseModel):
    messages: List[Message] = Field(
        description="对话历史消息，最后一条通常为用户输入"
    )
    control: Optional[ControlRequest] = Field(
        default=None,
        description="可选的控制操作描述；存在时优先按照结构化控制协议执行",
    )


class AgentInvokeResponse(BaseModel):
    message: Message = Field(description="Agent 的最终回复")
    raw_state: Optional[Dict[str, Any]] = Field(
        default=None, description="可选的原始 LangGraph 状态，便于调试"
    )
    control_result: Optional[ControlResult] = Field(
        default=None,
        description="高危控制操作（delete/hotswap/drain）的结构化结果",
    )
    agent_data: Optional[Dict[str, Any]] = Field(
        default=None,
        description="结构化的 Agent 步骤信息（thinking/tool/response），用于前端可视化。",
    )


class UserContext(BaseModel):
    user_id: Optional[str] = None
    role: Optional[str] = None
    tenant: Optional[str] = None


async def get_user_context(
    x_user_id: Optional[str] = Header(default=None, alias="X-User-Id"),
    x_user_role: Optional[str] = Header(default=None, alias="X-User-Role"),
    x_tenant: Optional[str] = Header(default=None, alias="X-Tenant"),
) -> UserContext:
    return UserContext(user_id=x_user_id, role=x_user_role, tenant=x_tenant)


def _normalize_role(role: Optional[str]) -> str:
    return (role or "").strip().lower()


def _check_permission(user: UserContext, op: str, mode: str) -> None:
    """
    基于 UserContext 的最小权限控制：

    - 所有用户均可发起 plan 模式（只读 dry-run）；
    - 高危 execute（pipeline.delete/hotswap/drain）仅允许 admin/operator；
    - 对于无权限用户抛出 PermissionError，由上层统一转换为 ControlResult.error。
    """

    if mode != "execute":
        return

    high_risk_ops = {
        "pipeline.delete",
        "pipeline.hotswap",
        "pipeline.drain",
    }
    if op not in high_risk_ops:
        return

    role = _normalize_role(user.role)
    allowed_roles = {"admin", "administrator", "operator"}
    if role in allowed_roles:
        return

    raise PermissionError(
        f"当前用户（role={user.role or 'unknown'}）无权执行 {op}（mode=execute），仅 admin/operator 可执行高危控制操作。"
    )


async def _invoke_structured_tool(tool: Any, args: Dict[str, Any]) -> Any:
    """
    以统一方式调用 LangChain Tool 实例，用于结构化 control 协议。

    - 若工具实现了 `ainvoke`，优先使用；
    - 否则回退到同步 `invoke`。
    """

    if hasattr(tool, "ainvoke"):
        return await tool.ainvoke(args)  # type: ignore[func-returns-value]
    return tool.invoke(args)  # type: ignore[func-returns-value]


async def _handle_control(
    control: ControlRequest,
    user: UserContext,
) -> Tuple[Message, ControlResult]:
    """
    处理结构化控制协议（delete/hotswap/drain）。

    所有高危操作统一采用两阶段模式：
    - mode=plan 仅调用 plan_* 工具，返回计划；
    - mode=execute 且 confirm=true 时才调用执行工具。
    """

    op = control.op
    mode = control.mode
    params = control.params

    # 最小权限校验：在进入具体逻辑前快速拒绝无权限操作
    _check_permission(user, op=op, mode=mode)

    try:
        if op == "pipeline.delete":
            pipeline_name = params.pipeline_name
            if not pipeline_name:
                raise ValueError("pipeline_name 不能为空")

            # 使用 plan_delete_pipeline_tool 生成删除计划（与自然语言路径复用同一实现）
            plan = await _invoke_structured_tool(
                plan_delete_pipeline_tool,
                {"pipeline_name": pipeline_name, "tenant": user.tenant},
            )

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=f"计划删除 pipeline '{pipeline_name}'，请在确认前检查相关影响。",
                )
                return msg, ControlResult(
                    op=op,
                    mode=mode,
                    success=True,
                    plan=plan,
                    plan_steps=[plan],
                )

            if not control.confirm:
                raise ValueError("执行删除前必须设置 confirm=true")

            result = await _invoke_structured_tool(
                delete_pipeline_tool,
                {"pipeline_name": pipeline_name, "confirm": True, "tenant": user.tenant},
            )
            msg = Message(
                role="assistant",
                content=f"已请求删除 pipeline '{pipeline_name}'，请关注 ControlPlane 审计与 VA 状态。",
            )
            return msg, ControlResult(
                op=op,
                mode=mode,
                success=True,
                plan=plan,
                plan_steps=[plan],
                result=result,
                execute_result=result,
            )

        if op == "pipeline.hotswap":
            pipeline_name = params.pipeline_name
            node = params.node
            model_uri = params.model_uri
            if not pipeline_name or not node or not model_uri:
                raise ValueError("pipeline_name/node/model_uri 不能为空")

            plan = await _invoke_structured_tool(
                plan_hotswap_model_tool,
                {
                    "pipeline_name": pipeline_name,
                    "node": node,
                    "model_uri": model_uri,
                    "tenant": user.tenant,
                },
            )

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=(
                        f"计划在 pipeline '{pipeline_name}' 的节点 '{node}' 上执行模型热切换 "
                        f"→ '{model_uri}'，请在确认前检查显存与兼容性。"
                    ),
                )
                return msg, ControlResult(
                    op=op,
                    mode=mode,
                    success=True,
                    plan=plan,
                    plan_steps=[plan],
                )

            if not control.confirm:
                raise ValueError("执行 hotswap 前必须设置 confirm=true")

            result = await _invoke_structured_tool(
                hotswap_model_tool,
                {
                    "pipeline_name": pipeline_name,
                    "node": node,
                    "model_uri": model_uri,
                    "confirm": True,
                    "tenant": user.tenant,
                },
            )
            msg = Message(
                role="assistant",
                content=(
                    f"已请求在 pipeline '{pipeline_name}' 的节点 '{node}' 上执行模型热切换，"
                    "请关注运行日志与指标变化。"
                ),
            )
            return msg, ControlResult(
                op=op,
                mode=mode,
                success=True,
                plan=plan,
                plan_steps=[plan],
                result=result,
                execute_result=result,
            )

        if op == "pipeline.drain":
            pipeline_name = params.pipeline_name
            timeout_sec = params.timeout_sec
            if not pipeline_name:
                raise ValueError("pipeline_name 不能为空")

            plan = await _invoke_structured_tool(
                plan_drain_pipeline_tool,
                {
                    "pipeline_name": pipeline_name,
                    "timeout_sec": timeout_sec,
                    "tenant": user.tenant,
                },
            )

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=(
                        f"计划对 pipeline '{pipeline_name}' 执行 drain，"
                        f"timeout_sec={timeout_sec if timeout_sec is not None else '默认'}。"
                    ),
                )
                return msg, ControlResult(
                    op=op,
                    mode=mode,
                    success=True,
                    plan=plan,
                    plan_steps=[plan],
                )

            if not control.confirm:
                raise ValueError("执行 drain 前必须设置 confirm=true")

            result = await _invoke_structured_tool(
                drain_pipeline_tool,
                {
                    "pipeline_name": pipeline_name,
                    "timeout_sec": timeout_sec,
                    "confirm": True,
                    "tenant": user.tenant,
                },
            )
            msg = Message(
                role="assistant",
                content=(
                    f"已请求对 pipeline '{pipeline_name}' 执行 drain，"
                    "请关注队列耗尽与 VA 状态。"
                ),
            )
            return msg, ControlResult(
                op=op,
                mode=mode,
                success=True,
                plan=plan,
                plan_steps=[plan],
                result=result,
                execute_result=result,
            )

        raise ValueError(f"不支持的控制操作类型: {op}")

    except Exception as exc:
        logger.exception("control operation failed: %s", exc)
        msg = Message(
            role="assistant",
            content=f"控制操作失败：{exc}",
        )
        return msg, ControlResult(
            op=control.op,
            mode=control.mode,
            success=False,
            error=str(exc),
        )


async def _invoke_agent_graph(
    messages: List[Tuple[str, str]],
    user: UserContext,
    thread_id: Optional[str],
) -> Dict[str, Any]:
    """
    Invoke the control-plane agent graph with provided messages.

    测试阶段：如果未配置 OPENAI_API_KEY，则不走远程 LLM，而是直接调用
    ControlPlane 的只读接口（例如 /api/pipelines），构造一个离线模式的回复。
    """

    settings = get_settings()

    # 当前 provider
    provider = getattr(settings, "llm_provider", "openai").lower()

    # 情况一：provider=openai 且缺少 OPENAI_API_KEY → 使用本地“假模型”直接查询 pipelines。
    if provider == "openai" and not settings.openai_api_key:
        pipelines = await _fetch_pipelines(tenant=user.tenant)
        if not pipelines:
            content = "当前处于本地测试模式（未配置 OPENAI_API_KEY），且未从 ControlPlane 查询到任何 pipeline。"
        else:
            lines = []
            for idx, p in enumerate(pipelines, start=1):
                name = p.get("name") or "<unnamed>"
                graph_id = p.get("graph_id")
                default_model_id = p.get("default_model_id")
                desc = f"{idx}. {name}"
                if graph_id is not None:
                    desc += f" (graph_id={graph_id})"
                if default_model_id is not None:
                    desc += f", default_model_id={default_model_id}"
                lines.append(desc)
            content = (
                "当前处于本地测试模式（未配置 OPENAI_API_KEY），"
                "已直接调用 ControlPlane 列出部分 pipeline：\n"
                + "\n".join(lines)
            )

        # 构造与 LangGraph 兼容的最小 state 结构，便于后续统一提取 message。
        state: Dict[str, Any] = {
            "messages": [
                ("user", messages[-1][1] if messages else ""),
                ("assistant", content),
            ],
            "offline": True,
            "pipelines": pipelines,
            "thread_id": thread_id,
        }
        return state

    # 情况二：其余情况（包括 provider=ollama，或 provider=openai 且已配置 OPENAI_API_KEY） →
    # 统一走预构建 ReAct Agent，由大模型根据工具描述与上下文自行决定是否调用工具。
    agent_graph = get_control_plane_agent()
    state = build_state_from_tuples(messages)

    # 为无 thread_id 的一问一答调用分配独立虚拟线程，避免复用历史导致 LangGraph
    # 出现“不匹配的 tool_calls/ToolMessage”错误。
    from uuid import uuid4
    effective_thread_id = thread_id or f"invoke-{uuid4()}"

    # 把用户上下文附加到 config 中，后续可用于权限控制与审计
    config: Dict[str, Any] = {
        "configurable": {
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": effective_thread_id,
        }
    }

    # 兼容同步/异步 Graph 接口，并在出现已知的“聊天历史不一致”错误时做一次自愈重试：
    # 当线程历史中残留带 tool_calls 但缺少对应 ToolMessage 的 AIMessage 时，
    # LangGraph 会抛出 INVALID_CHAT_HISTORY，此时改用新的 thread_id 重新开始该轮调用。
    try:
        if hasattr(agent_graph, "ainvoke"):
            result = await agent_graph.ainvoke(state, config=config)  # type: ignore[call-arg]
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: agent_graph.invoke(state, config=config)
            )
        return result
    except ValueError as exc:
        msg = str(exc)
        if "Found AIMessages with tool_calls" not in msg:
            logger.exception("agent_graph invoke failed: %s", exc)
            raise

        # 已知的 INVALID_CHAT_HISTORY 场景：尝试用全新的虚拟线程重试一次，
        # 避免单个损坏线程状态让对话永久失效。
        logger.warning(
            "agent_graph invalid chat history for thread_id=%s, resetting thread and retrying once",
            effective_thread_id,
        )
        from uuid import uuid4

        reset_thread_id = f"reset-{uuid4()}"
        reset_config: Dict[str, Any] = {
            "configurable": {
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "thread_id": reset_thread_id,
            }
        }
        if hasattr(agent_graph, "ainvoke"):
            return await agent_graph.ainvoke(state, config=reset_config)  # type: ignore[call-arg]
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None, lambda: agent_graph.invoke(state, config=reset_config)
        )


def _to_lc_messages(messages: List[Message]) -> List[BaseMessage]:
    """将 HTTP 层的 Message 转换为 LangChain BaseMessage 列表。"""

    out: List[BaseMessage] = []
    for m in messages:
        if m.role == "user":
            out.append(HumanMessage(content=m.content))
        elif m.role == "assistant":
            out.append(AIMessage(content=m.content))
        elif m.role == "system":
            out.append(SystemMessage(content=m.content))
        else:
            # tool 或未知角色：先按 assistant 文本处理，后续如有需要再细分
            out.append(AIMessage(content=m.content))
    return out


def _build_agent_data_from_state(state: Dict[str, Any]) -> Dict[str, Any]:
    """
    从 LangGraph state 中提取结构化步骤信息，近似 openAgent 的 agent_data.steps 结构。

    - type: user / thinking / tool / response
    - content: 简要文本
    - tool_name/tool_call_id: 对于工具调用步骤的附加信息
    """

    raw_messages: List[Any] = state.get("messages", []) or []
    steps: List[Dict[str, Any]] = []
    step_id = 0

    def add_step(**kwargs: Any) -> None:
        nonlocal step_id
        data = {"id": step_id}
        data.update(kwargs)
        steps.append(data)
        step_id += 1

    for m in raw_messages:
        role = None
        content: str = ""
        tool_calls: Any = None
        tool_call_id: str | None = None

        if isinstance(m, tuple) and len(m) >= 2:
            role = str(m[0])
            content = str(m[1])
        elif isinstance(m, dict):
            role = m.get("type") or m.get("role")
            content = str(m.get("content") or "")
            tool_calls = m.get("tool_calls") or []
            tool_call_id = m.get("tool_call_id")
        else:
            role = getattr(m, "type", getattr(m, "role", None))
            if role == "ai":
                role = "assistant"
            content = str(getattr(m, "content", m))
            tool_calls = getattr(m, "tool_calls", None)
            tool_call_id = getattr(m, "tool_call_id", None)

        if role in ("user", "human"):
            add_step(type="user", content=content)
        elif role in ("assistant", "ai"):
            # 如果包含工具调用，则视为思考 + 工具计划
            if tool_calls:
                add_step(type="thinking", content=content or "大模型正在规划工具调用")
                for call in tool_calls:
                    if isinstance(call, dict):
                        name = call.get("name") or ""
                        cid = call.get("id") or ""
                    else:
                        name = getattr(call, "name", "") or ""
                        cid = getattr(call, "id", "") or ""
                    add_step(
                        type="tool",
                        tool_name=name,
                        tool_call_id=cid,
                        content=f"准备调用工具 {name or 'unknown'}",
                        status="pending",
                    )
            else:
                add_step(type="response", content=content, status="ok")
        elif role == "tool":
            add_step(
                type="tool",
                content=content,
                tool_call_id=tool_call_id,
                status="success",
            )

    return {"status": "done", "steps": steps}


async def _invoke_stategraph_agent(
    request_messages: List[Message],
    user: UserContext,
    thread_id: Optional[str],
) -> Dict[str, Any]:
    """
    调用基于 StateGraph 的实验性 Agent。

    - 若未配置 OPENAI_API_KEY，则复用现有 _invoke_agent_graph 的离线逻辑；
    - 否则将 HTTP messages 转为 BaseMessage 列表，并以 AgentState 形式交给 StateGraph。
    """

    settings = get_settings()

    # 复用离线 fallback 逻辑：仅在 provider=openai 且缺少 OPENAI_API_KEY 时走本地模式；
    # 当 provider=ollama 时，即使没有 OPENAI_API_KEY 也始终调用远程 LLM。
    provider = getattr(settings, "llm_provider", "openai").lower()
    if provider == "openai" and not settings.openai_api_key:
        message_tuples: List[Tuple[str, str]] = [
            (m.role, m.content) for m in request_messages
        ]
        return await _invoke_agent_graph(message_tuples, user=user, thread_id=thread_id)

    agent_graph = get_stategraph_agent()
    lc_messages = _to_lc_messages(request_messages)

    state_in: Dict[str, Any] = AgentState(
        messages=lc_messages,
        user={"user_id": user.user_id, "role": user.role, "tenant": user.tenant},
        cv_context={},
        plan=[],
        pending_tools=[],
        task=None,
        last_control_op=None,
        last_control_mode=None,
        last_control_result=None,
    ).dict()

    settings = get_settings()
    config: Dict[str, Any] = {
        "configurable": {
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        },
        # 限制 StateGraph 递归深度，避免 agent→tools→agent 无止境循环
        "recursion_limit": max(4, int(getattr(settings, "recursion_limit", 12))),
    }

    # 兼容同步/异步 Graph 接口，并对递归超限单独兜底
    try:
        if hasattr(agent_graph, "ainvoke"):
            result = await agent_graph.ainvoke(state_in, config=config)  # type: ignore[call-arg]
        else:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None, lambda: agent_graph.invoke(state_in, config=config)
            )
    except GraphRecursionError as exc:
        logger.warning("stategraph recursion_limit reached: %s", exc)
        # 返回一条友好的错误提示，而不是 500
        return {
            "messages": lc_messages
            + [
                AIMessage(
                    content="Agent 在当前问题上的思考与工具调用步数超过上限，请缩小问题范围或分步提问后重试。"
                )
            ]
        }

    # StateGraph 返回的 result 即为最新状态 dict
    if isinstance(result, AgentState):
        return result.dict()
    if isinstance(result, dict):
        return result
    # 兜底：包装为状态字典
    return {"messages": lc_messages + [AIMessage(content=str(result))]}


def _extract_reply_message(state: Dict[str, Any]) -> Message:
    """从 LangGraph 状态中提取最后一条 AI 回复，并转换为 API Message。"""

    messages: List[Any] = state.get("messages", [])
    if not messages:
        return Message(role="assistant", content="")

    last = messages[-1]

    # LangGraph / LangChain 输出可能是 BaseMessage 或 (role, content) 元组
    if isinstance(last, tuple) and len(last) >= 2:
        role = str(last[0]) or "assistant"
        content = str(last[1])
    else:
        role = getattr(last, "type", "assistant")
        if role == "ai":
            role = "assistant"
        content = getattr(last, "content", str(last))

    if role not in ("user", "assistant", "system", "tool"):
        role = "assistant"

    return Message(role=role, content=content)


@app.get("/healthz")
async def healthz() -> Dict[str, str]:
    """Health check endpoint."""

    return {"status": "ok"}


@app.post("/v1/agent/excel/chart", response_model=ExcelAgentResponse)
async def excel_chart(
    request: ExcelAnalysisRequest,
) -> ExcelAgentResponse:
    """Excel 分析与图表生成接口。

    输入 Excel 文件标识与自然语言问题，返回可直接用于前端渲染的 ECharts 配置与分析结论。
    """

    start_ts = asyncio.get_event_loop().time()
    logger.info(
        "excel_chart start",
        extra={
            "session_id": request.session_id,
            "file_id": request.file_id,
            "sheet_name": request.sheet_name,
        },
    )

    loop = asyncio.get_running_loop()
    try:
        response = await loop.run_in_executor(
            None, lambda: invoke_excel_chart_agent(request)
        )
    except FileNotFoundError as exc:
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.warning(
            "excel_chart file not found",
            extra={
                "session_id": request.session_id,
                "file_id": request.file_id,
                "sheet_name": request.sheet_name,
                "duration_ms": duration_ms,
            },
        )
        raise HTTPException(status_code=400, detail=str(exc))
    except Exception as exc:
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.exception(
            "excel_chart failed",
            extra={
                "session_id": request.session_id,
                "file_id": request.file_id,
                "sheet_name": request.sheet_name,
                "duration_ms": duration_ms,
            },
        )
        raise HTTPException(status_code=500, detail="Excel 分析失败，请稍后重试") from exc

    duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
    logger.info(
        "excel_chart done",
        extra={
            "session_id": request.session_id,
            "file_id": request.file_id,
            "sheet_name": request.sheet_name,
            "duration_ms": duration_ms,
        },
    )
    _record_http_metrics("/v1/agent/excel/chart", "POST", duration_ms)

    return response


@app.post("/v1/agent/db/chart", response_model=DbAgentResponse)
async def db_chart(
    request: DbAnalysisRequest,
    user: UserContext = Depends(get_user_context),
) -> DbAgentResponse:
    """数据库分析与图表生成接口。

    输入数据库名称（可选）与自然语言问题，由内部的 LangChain SQLDatabase + SQL Agent 生成并执行只读 SQL，
    自动选择合适的表/维度/指标与图表类型，返回 ECharts 配置与分析结论。
    """

    start_ts = asyncio.get_event_loop().time()
    logger.info(
        "db_chart start",
        extra={
            "session_id": request.session_id,
            "db_name": request.db_name,
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
        },
    )

    loop = asyncio.get_running_loop()
    try:
        user_ctx = {
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
        }
        response = await loop.run_in_executor(
            None, lambda: invoke_db_chart_agent(request, user=user_ctx)
        )
    except TimeoutError as exc:
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.warning(
            "db_chart timeout",
            extra={
                "session_id": request.session_id,
                "db_name": request.db_name,
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "duration_ms": duration_ms,
            },
        )
        raise HTTPException(
            status_code=504,
            detail=str(exc) or "数据库分析超时，请稍后重试",
        ) from exc
    except Exception as exc:
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.exception(
            "db_chart failed",
            extra={
                "session_id": request.session_id,
                "db_name": request.db_name,
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "duration_ms": duration_ms,
            },
        )
        raise HTTPException(status_code=500, detail="数据库分析失败，请稍后重试") from exc

    duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
    logger.info(
        "db_chart done",
        extra={
            "session_id": request.session_id,
            "db_name": request.db_name,
            "used_db_name": response.used_db_name,
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "sql_agent_used": True,
            "sql_count": len(response.charts),
            "rows_total": sum(
                max(0, len((chart.option.get("dataset", {}) or {}).get("source", [])) - 1)
                if isinstance(chart.option.get("dataset", {}), dict)
                else 0
                for chart in response.charts
            ),
            "duration_ms": duration_ms,
        },
    )
    _record_http_metrics("/v1/agent/db/chart", "POST", duration_ms)

    return response


@app.post("/v1/agent/invoke", response_model=AgentInvokeResponse)
async def agent_invoke(
    request: AgentInvokeRequest,
    user: UserContext = Depends(get_user_context),
) -> AgentInvokeResponse:
    """一问一答形式调用 Agent（MVP 阶段，无显式线程标识）。"""

    # 若包含结构化控制描述，则优先按控制协议执行，不使用 LLM
    if request.control is not None:
        start_ts = asyncio.get_event_loop().time()
        logger.info(
            "agent_invoke control start",
            extra={
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "thread_id": None,
                "op": request.control.op,
                "mode": request.control.mode,
            },
        )
        msg, control_result = await _handle_control(request.control, user=user)
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.info(
            "agent_invoke control done",
            extra={
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "thread_id": None,
                "op": request.control.op,
                "mode": request.control.mode,
                "success": control_result.success,
                "duration_ms": duration_ms,
            },
        )
        try:
            update_summary_for_control(
                thread_id=None,
                user=user,
                control_result=control_result,
            )
        except Exception:  # pragma: no cover - 容错
            logger.warning("update_summary_for_control failed for agent_invoke", exc_info=True)
        return AgentInvokeResponse(
            message=msg,
            raw_state=None,
            control_result=control_result,
            agent_data=None,
        )

    start_ts = asyncio.get_event_loop().time()
    logger.info(
        "agent_invoke start",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": None,
        },
    )

    state = await _invoke_stategraph_agent(
        request_messages=request.messages,
        user=user,
        thread_id=None,
    )
    reply = _extract_reply_message(state)

    duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
    logger.info(
        "agent_invoke done",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": None,
            "duration_ms": duration_ms,
        },
    )
    _record_http_metrics("/v1/agent/invoke", "POST", duration_ms)

    try:
        update_summary_for_messages(
            thread_id=None,
            user=user,
            messages=request.messages + [reply],
        )
    except Exception:  # pragma: no cover - 容错
        logger.warning("update_summary_for_messages failed for agent_invoke", exc_info=True)

    agent_data: Optional[Dict[str, Any]] = None
    try:
        if isinstance(state, dict):
            agent_data = _build_agent_data_from_state(state)
    except Exception:  # pragma: no cover - 容错
        logger.warning("build_agent_data_from_state failed for agent_invoke", exc_info=True)

    return AgentInvokeResponse(message=reply, raw_state=state, control_result=None, agent_data=agent_data)


@app.post("/v1/agent/threads/{thread_id}/invoke", response_model=AgentInvokeResponse)
async def agent_thread_invoke(
    thread_id: str,
    request: AgentInvokeRequest,
    user: UserContext = Depends(get_user_context),
) -> AgentInvokeResponse:
    """
    带 thread_id 的多轮对话接口。

    依赖 LangGraph 的 checkpoint 机制按 thread_id 维度保存对话状态；
    当前实现基于 MemorySaver，仅在单进程内生效。
    """

    if request.control is not None:
        start_ts = asyncio.get_event_loop().time()
        logger.info(
            "agent_thread_invoke control start",
            extra={
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "thread_id": thread_id,
                "op": request.control.op,
                "mode": request.control.mode,
            },
        )
        msg, control_result = await _handle_control(request.control, user=user)
        duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
        logger.info(
            "agent_thread_invoke control done",
            extra={
                "user_id": user.user_id,
                "role": user.role,
                "tenant": user.tenant,
                "thread_id": thread_id,
                "op": request.control.op,
                "mode": request.control.mode,
                "success": control_result.success,
                "duration_ms": duration_ms,
            },
        )
        try:
            update_summary_for_control(
                thread_id=thread_id,
                user=user,
                control_result=control_result,
            )
        except Exception:  # pragma: no cover - 容错
            logger.warning(
                "update_summary_for_control failed for thread %s", thread_id, exc_info=True
            )
        return AgentInvokeResponse(
            message=msg,
            raw_state=None,
            control_result=control_result,
            agent_data=None,
        )

    start_ts = asyncio.get_event_loop().time()
    logger.info(
        "agent_thread_invoke start",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        },
    )

    state = await _invoke_stategraph_agent(
        request_messages=request.messages,
        user=user,
        thread_id=thread_id,
    )
    reply = _extract_reply_message(state)

    duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
    logger.info(
        "agent_thread_invoke done",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
            "duration_ms": duration_ms,
        },
    )
    _record_http_metrics("/v1/agent/threads/{thread_id}/invoke", "POST", duration_ms)

    try:
        update_summary_for_messages(
            thread_id=thread_id,
            user=user,
            messages=request.messages + [reply],
        )
    except Exception:  # pragma: no cover - 容错
        logger.warning(
            "update_summary_for_messages failed for thread %s", thread_id, exc_info=True
        )

    agent_data = None
    try:
        if isinstance(state, dict):
            agent_data = _build_agent_data_from_state(state)
    except Exception:  # pragma: no cover - 容错
        logger.warning(
            "build_agent_data_from_state failed for thread %s", thread_id, exc_info=True
        )

    return AgentInvokeResponse(message=reply, raw_state=state, control_result=None, agent_data=agent_data)


@app.post("/v1/agent/stategraph/threads/{thread_id}/invoke", response_model=AgentInvokeResponse)
async def agent_stategraph_thread_invoke(
    thread_id: str,
    request: AgentInvokeRequest,
    user: UserContext = Depends(get_user_context),
) -> AgentInvokeResponse:
    """实验性：基于 StateGraph 的多轮对话接口（保留向后兼容的独立入口）。"""

    start_ts = asyncio.get_event_loop().time()
    logger.info(
        "agent_stategraph_thread_invoke start",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        },
    )

    state = await _invoke_stategraph_agent(
        request_messages=request.messages,
        user=user,
        thread_id=thread_id,
    )
    reply = _extract_reply_message(state)

    duration_ms = (asyncio.get_event_loop().time() - start_ts) * 1000.0
    logger.info(
        "agent_stategraph_thread_invoke done",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
            "duration_ms": duration_ms,
        },
    )
    _record_http_metrics(
        "/v1/agent/stategraph/threads/{thread_id}/invoke", "POST", duration_ms
    )

    try:
        update_summary_for_messages(
            thread_id=thread_id,
            user=user,
            messages=request.messages + [reply],
        )
    except Exception:  # pragma: no cover - 容错
        logger.warning(
            "update_summary_for_messages failed for stategraph thread %s",
            thread_id,
            exc_info=True,
        )

    agent_data = None
    try:
        if isinstance(state, dict):
            agent_data = _build_agent_data_from_state(state)
    except Exception:  # pragma: no cover - 容错
        logger.warning(
            "build_agent_data_from_state failed for stategraph thread %s",
            thread_id,
            exc_info=True,
        )

    # raw_state 暂不返回（StateGraph 状态包含 BaseMessage，序列化开销较大），仅返回最终回复
    return AgentInvokeResponse(message=reply, raw_state=None, control_result=None, agent_data=agent_data)


@app.get("/v1/agent/threads", response_model=List[Dict[str, Any]])
async def list_agent_threads() -> List[Dict[str, Any]]:
    """返回当前进程内已记录的线程摘要列表（用于前端线程视图）。"""

    return list_thread_summaries()


@app.get("/v1/agent/threads/{thread_id}/summary", response_model=Dict[str, Any])
async def get_agent_thread_summary(thread_id: str) -> Dict[str, Any]:
    """按 thread_id 查询最近一次对话与控制操作摘要。"""

    summary = get_thread_summary(thread_id)
    if summary is None:
        return {
            "thread_id": thread_id,
            "last_user_message": None,
            "last_assistant_message": None,
            "last_control_op": None,
            "last_control_mode": None,
            "last_control_success": None,
            "last_error": None,
            "updated_at": None,
        }
    return summary


@app.get("/v1/agent/stats", response_model=List[Dict[str, Any]])
async def get_agent_control_stats() -> List[Dict[str, Any]]:
    """返回 Agent 控制操作按 (op, mode) 聚合的统计信息。"""

    return get_agent_stats()
