import asyncio
import logging
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import Depends, FastAPI, Header
from pydantic import BaseModel, Field

from ..config import get_settings
from ..graph import build_state_from_tuples, get_control_plane_agent
from ..tools.pipelines import (
    _fetch_pipelines,
    _fetch_pipeline_status,
    _call_delete_pipeline,
    _call_hotswap_model,
    _call_drain_pipeline,
)


logger = logging.getLogger("cv_agent")


def _configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )


_configure_logging()

app = FastAPI(title="CV Agent Service", version="0.1.0")


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

    try:
        if op == "pipeline.delete":
            pipeline_name = params.pipeline_name
            if not pipeline_name:
                raise ValueError("pipeline_name 不能为空")

            # 生成删除计划（直接使用底层 _fetch_pipelines）
            pipelines = await _fetch_pipelines()
            target = None
            for pipeline in pipelines:
                if pipeline.get("name") == pipeline_name:
                    target = pipeline
                    break

            if target is None:
                plan: Dict[str, Any] = {
                    "pipeline_name": pipeline_name,
                    "found": False,
                    "reason": "pipeline_not_found",
                }
            else:
                plan = {
                    "pipeline_name": pipeline_name,
                    "found": True,
                    "plan": {
                        "action": "delete",
                        "graph_id": target.get("graph_id"),
                        "default_model_id": target.get("default_model_id"),
                    },
                }

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=f"计划删除 pipeline '{pipeline_name}'，请在确认前检查相关影响。",
                )
                return msg, ControlResult(
                    op=op, mode=mode, success=True, plan=plan
                )

            if not control.confirm:
                raise ValueError("执行删除前必须设置 confirm=true")

            result = await _call_delete_pipeline(pipeline_name=pipeline_name)
            msg = Message(
                role="assistant",
                content=f"已请求删除 pipeline '{pipeline_name}'，请关注 ControlPlane 审计与 VA 状态。",
            )
            return msg, ControlResult(
                op=op, mode=mode, success=True, plan=plan, result=result
            )

        if op == "pipeline.hotswap":
            pipeline_name = params.pipeline_name
            node = params.node
            model_uri = params.model_uri
            if not pipeline_name or not node or not model_uri:
                raise ValueError("pipeline_name/node/model_uri 不能为空")

            pipelines = await _fetch_pipelines()
            exists = any(
                pipeline.get("name") == pipeline_name for pipeline in pipelines
            )
            plan = {
                "pipeline_name": pipeline_name,
                "exists": exists,
                "plan": {
                    "action": "hotswap",
                    "node": node,
                    "model_uri": model_uri,
                },
            }

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=(
                        f"计划在 pipeline '{pipeline_name}' 的节点 '{node}' 上执行模型热切换 "
                        f"→ '{model_uri}'，请在确认前检查显存与兼容性。"
                    ),
                )
                return msg, ControlResult(
                    op=op, mode=mode, success=True, plan=plan
                )

            if not control.confirm:
                raise ValueError("执行 hotswap 前必须设置 confirm=true")

            result = await _call_hotswap_model(
                pipeline_name=pipeline_name,
                node=node,
                model_uri=model_uri,
            )
            msg = Message(
                role="assistant",
                content=(
                    f"已请求在 pipeline '{pipeline_name}' 的节点 '{node}' 上执行模型热切换，"
                    "请关注运行日志与指标变化。"
                ),
            )
            return msg, ControlResult(
                op=op, mode=mode, success=True, plan=plan, result=result
            )

        if op == "pipeline.drain":
            pipeline_name = params.pipeline_name
            timeout_sec = params.timeout_sec
            if not pipeline_name:
                raise ValueError("pipeline_name 不能为空")

            pipelines = await _fetch_pipelines()
            exists = any(
                pipeline.get("name") == pipeline_name for pipeline in pipelines
            )
            status = await _fetch_pipeline_status(pipeline_name)
            plan = {
                "pipeline_name": pipeline_name,
                "exists": exists,
                "plan": {
                    "action": "drain",
                    "timeout_sec": timeout_sec,
                },
                "current_status": status,
            }

            if mode == "plan":
                msg = Message(
                    role="assistant",
                    content=(
                        f"计划对 pipeline '{pipeline_name}' 执行 drain，"
                        f"timeout_sec={timeout_sec if timeout_sec is not None else '默认'}。"
                    ),
                )
                return msg, ControlResult(
                    op=op, mode=mode, success=True, plan=plan
                )

            if not control.confirm:
                raise ValueError("执行 drain 前必须设置 confirm=true")

            result = await _call_drain_pipeline(
                pipeline_name=pipeline_name,
                timeout_sec=timeout_sec,
            )
            msg = Message(
                role="assistant",
                content=(
                    f"已请求对 pipeline '{pipeline_name}' 执行 drain，"
                    "请关注队列耗尽与 VA 状态。"
                ),
            )
            return msg, ControlResult(
                op=op, mode=mode, success=True, plan=plan, result=result
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

    # Offline fallback: no API key → 使用本地“假模型”直接查询 pipelines。
    if not settings.openai_api_key:
        pipelines = await _fetch_pipelines()
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

    agent_graph = get_control_plane_agent()
    state = build_state_from_tuples(messages)

    # 把用户上下文附加到 config 或 state 中，后续可用于权限控制与审计
    config: Dict[str, Any] = {
        "configurable": {
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        }
    }

    # 兼容同步/异步 Graph 接口
    if hasattr(agent_graph, "ainvoke"):
        result = await agent_graph.ainvoke(state, config=config)  # type: ignore[call-arg]
    else:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(
            None, lambda: agent_graph.invoke(state, config=config)
        )

    return result


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


@app.post("/v1/agent/invoke", response_model=AgentInvokeResponse)
async def agent_invoke(
    request: AgentInvokeRequest,
    user: UserContext = Depends(get_user_context),
) -> AgentInvokeResponse:
    """一问一答形式调用 Agent（MVP 阶段，无显式线程标识）。"""

    # 若包含结构化控制描述，则优先按控制协议执行，不使用 LLM
    if request.control is not None:
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
            },
        )
        return AgentInvokeResponse(
            message=msg,
            raw_state=None,
            control_result=control_result,
        )

    message_tuples: List[Tuple[str, str]] = [
        (msg.role, msg.content) for msg in request.messages
    ]

    logger.info(
        "agent_invoke start",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": None,
        },
    )

    state = await _invoke_agent_graph(message_tuples, user=user, thread_id=None)
    reply = _extract_reply_message(state)

    logger.info(
        "agent_invoke done",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": None,
        },
    )

    return AgentInvokeResponse(message=reply, raw_state=state)


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
            },
        )
        return AgentInvokeResponse(
            message=msg,
            raw_state=None,
            control_result=control_result,
        )

    message_tuples: List[Tuple[str, str]] = [
        (msg.role, msg.content) for msg in request.messages
    ]

    logger.info(
        "agent_thread_invoke start",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        },
    )

    state = await _invoke_agent_graph(
        message_tuples,
        user=user,
        thread_id=thread_id,
    )
    reply = _extract_reply_message(state)

    logger.info(
        "agent_thread_invoke done",
        extra={
            "user_id": user.user_id,
            "role": user.role,
            "tenant": user.tenant,
            "thread_id": thread_id,
        },
    )

    return AgentInvokeResponse(message=reply, raw_state=state)
