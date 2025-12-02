from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

from ..config import get_settings
import logging

logger = logging.getLogger("cv_agent")

try:  # LangChain 1.x preferred import path
    from langchain_core.tools import tool
except Exception:  # pragma: no cover - fallback for older layouts
    try:
        from langchain.tools import tool  # type: ignore[no-redef]
    except Exception:

        # If LangChain is not installed yet, fall back to a no-op decorator
        def tool(*args: Any, **kwargs: Any):  # type: ignore[misc]
            def decorator(func: Any) -> Any:
                return func

            return decorator


class ListPipelinesInput(BaseModel):
    """Input schema for list_pipelines tool."""

    limit: Optional[int] = Field(
        default=None,
        description="Optional maximum number of pipelines to return",
        ge=1,
    )


async def _fetch_pipelines(
    limit: Optional[int] = None,
    *,
    tenant: Optional[str] = None,
) -> List[dict]:
    """Fetch pipeline list from ControlPlane HTTP API.

    为了避免单个 HTTP 调用失败导致整个 Agent 图报错，这里对下游超时和
    HTTP 错误做了容错处理：记录日志并返回空列表。
    """

    settings = get_settings()
    url = settings.cp_base_url.rstrip("/") + "/api/pipelines"

    headers: Dict[str, str] = {}
    if tenant:
        headers["X-Tenant"] = tenant

    try:
        async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
            response = await client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:  # pragma: no cover - 运行时容错
        logger.warning(
            "list_pipelines: fetch pipelines failed: exc=%r cp_base_url=%r url=%r",
            exc,
            settings.cp_base_url,
            url,
        )
        return []

    items = payload.get("data", []) if isinstance(payload, dict) else []
    if not isinstance(items, list):
        return []

    if limit is not None:
        items = items[:limit]

    simplified: List[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        simplified.append(
            {
                "name": item.get("name"),
                "graph_id": item.get("graph_id"),
                "default_model_id": item.get("default_model_id"),
            }
        )

    return simplified


@tool("list_pipelines")
async def list_pipelines_tool(
    limit: Optional[int] = None,
    tenant: Optional[str] = None,
) -> List[dict]:
    """
    列出当前 ControlPlane 中已配置的 pipelines。

    仅执行只读查询，不会对系统状态产生任何修改。
    """

    return await _fetch_pipelines(limit=limit, tenant=tenant)


class GetPipelineStatusInput(BaseModel):
    """Input schema for get_pipeline_status tool."""

    pipeline_name: str = Field(description="要查询状态的 pipeline 名称")


async def _fetch_pipeline_status(
    pipeline_name: str,
    *,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Fetch pipeline status from ControlPlane HTTP API."""

    settings = get_settings()
    base = settings.cp_base_url.rstrip("/")
    url = f"{base}/api/control/status"

    params = {"pipeline_name": pipeline_name}

    headers: Dict[str, str] = {}
    if tenant:
        headers["X-Tenant"] = tenant

    async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
        response = await client.get(url, params=params, headers=headers)
        response.raise_for_status()
        payload = response.json()

    if not isinstance(payload, dict):
        return {"pipeline_name": pipeline_name, "phase": None, "metrics": None}

    data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
    phase = data.get("phase") if isinstance(data, dict) else None
    metrics = data.get("metrics") if isinstance(data, dict) else None

    return {
        "pipeline_name": pipeline_name,
        "phase": phase,
        "metrics": metrics,
    }


@tool("get_pipeline_status")
async def get_pipeline_status_tool(
    pipeline_name: str,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    查询指定 pipeline 在 VA 中的当前运行状态与指标。

    该工具调用 ControlPlane 的 `/api/control/status` 接口，仅进行只读查询。
    """

    return await _fetch_pipeline_status(pipeline_name=pipeline_name, tenant=tenant)


class PlanUpdatePipelineConfigInput(BaseModel):
    """Input schema for plan_update_pipeline_config tool (dry-run only)."""

    pipeline_name: str = Field(description="要更新的 pipeline 名称")
    new_graph_id: Optional[str] = Field(
        default=None,
        description="新的 graph_id（可选，未提供则保持不变）",
    )
    new_default_model_id: Optional[str] = Field(
        default=None,
        description="新的默认模型 ID（可选，未提供则保持不变）",
    )


@tool("plan_update_pipeline_config")
async def plan_update_pipeline_config_tool(
    pipeline_name: str,
    new_graph_id: Optional[str] = None,
    new_default_model_id: Optional[str] = None,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    仅执行 **dry-run** 的 pipeline 配置更新规划工具。

    - 会从 ControlPlane 查询当前 pipeline 列表；
    - 找到指定 pipeline 的现有配置（graph_id/default_model_id）；
    - 与请求中的新值进行对比，返回 diff 结果；
    - **不会** 调用任何实际写操作接口，仅用于人机协同阶段的变更预览。
    """

    pipelines = await _fetch_pipelines(tenant=tenant)
    current: Optional[Dict[str, Any]] = None
    for pipeline in pipelines:
        if pipeline.get("name") == pipeline_name:
            current = pipeline
            break

    if current is None:
        return {
            "pipeline_name": pipeline_name,
            "found": False,
            "reason": "pipeline_not_found",
        }

    desired_graph_id = (
        new_graph_id
        if new_graph_id is not None
        else current.get("graph_id")
    )
    desired_default_model_id = (
        new_default_model_id
        if new_default_model_id is not None
        else current.get("default_model_id")
    )

    diff: Dict[str, Any] = {
        "pipeline_name": pipeline_name,
        "found": True,
        "changes": {},
        "current": {
            "graph_id": current.get("graph_id"),
            "default_model_id": current.get("default_model_id"),
        },
        "desired": {
            "graph_id": desired_graph_id,
            "default_model_id": desired_default_model_id,
        },
    }

    if desired_graph_id != current.get("graph_id"):
        diff["changes"]["graph_id"] = {
            "from": current.get("graph_id"),
            "to": desired_graph_id,
        }

    if desired_default_model_id != current.get("default_model_id"):
        diff["changes"]["default_model_id"] = {
            "from": current.get("default_model_id"),
            "to": desired_default_model_id,
        }

    return diff


class PlanDeletePipelineInput(BaseModel):
    """Input schema for plan_delete_pipeline tool (dry-run only)."""

    pipeline_name: str = Field(description="计划删除的 pipeline 名称")


@tool("plan_delete_pipeline")
async def plan_delete_pipeline_tool(
    pipeline_name: str,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    仅执行 **dry-run** 的 pipeline 删除规划工具。

    - 从 `/api/pipelines` 中检查目标是否存在；
    - 返回包含 pipeline 基本信息的删除计划；
    - **不会** 调用任何删除接口。
    """

    pipelines = await _fetch_pipelines(tenant=tenant)
    target: Optional[Dict[str, Any]] = None
    for pipeline in pipelines:
        if pipeline.get("name") == pipeline_name:
            target = pipeline
            break

    if target is None:
        return {
            "pipeline_name": pipeline_name,
            "found": False,
            "reason": "pipeline_not_found",
        }

    return {
        "pipeline_name": pipeline_name,
        "found": True,
        "plan": {
            "action": "delete",
            "graph_id": target.get("graph_id"),
            "default_model_id": target.get("default_model_id"),
        },
    }


class DeletePipelineInput(BaseModel):
    """Input schema for delete_pipeline tool."""

    pipeline_name: str = Field(description="要删除的 pipeline 名称")
    confirm: bool = Field(
        default=False,
        description="必须为 true 才会执行实际删除；false 时仅返回计划",
    )


async def _call_delete_pipeline(
    pipeline_name: str,
    *,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Call CP DELETE /api/control/pipeline to remove a pipeline by name."""

    settings = get_settings()
    base = settings.cp_base_url.rstrip("/")
    url = f"{base}/api/control/pipeline"

    headers: Dict[str, str] = {}
    if tenant:
        headers["X-Tenant"] = tenant

    async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
        response = await client.delete(
            url,
            params={"pipeline_name": pipeline_name},
            headers=headers,
        )
        try:
            payload = response.json()
        except Exception:
            payload = None

    return {
        "status_code": response.status_code,
        "payload": payload,
    }


@tool("delete_pipeline")
async def delete_pipeline_tool(
    pipeline_name: str,
    confirm: bool = False,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    删除指定 pipeline 的高危工具。

    约束：
    - 若 `confirm=false`（默认），仅返回删除计划，不执行实际删除；
    - 若 `confirm=true`，则调用 CP `/api/control/pipeline` 触发删除。
    """

    plan = await plan_delete_pipeline_tool(pipeline_name=pipeline_name, tenant=tenant)

    if not confirm:
        return {"mode": "dry-run", "plan": plan}

    result = await _call_delete_pipeline(pipeline_name=pipeline_name, tenant=tenant)
    return {"mode": "execute", "plan": plan, "result": result}


class PlanHotswapModelInput(BaseModel):
    """Input schema for plan_hotswap_model tool (dry-run only)."""

    pipeline_name: str = Field(description="目标 pipeline 名称")
    node: str = Field(description="要 hotswap 的节点名称")
    model_uri: str = Field(description="新的模型 URI（例如 s3://... 或本地路径）")


@tool("plan_hotswap_model")
async def plan_hotswap_model_tool(
    pipeline_name: str,
    node: str,
    model_uri: str,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    仅执行 **dry-run** 的 hotswap 规划工具。

    - 检查 pipeline 是否存在；
    - 返回包含 pipeline/node/model_uri 的变更计划；
    - 不调用实际 `/api/control/hotswap` 接口。
    """

    pipelines = await _fetch_pipelines(tenant=tenant)
    exists = any(pipeline.get("name") == pipeline_name for pipeline in pipelines)

    return {
        "pipeline_name": pipeline_name,
        "exists": exists,
        "plan": {
            "action": "hotswap",
            "node": node,
            "model_uri": model_uri,
        },
    }


class HotswapModelInput(BaseModel):
    """Input schema for hotswap_model tool."""

    pipeline_name: str = Field(description="目标 pipeline 名称")
    node: str = Field(description="要 hotswap 的节点名称")
    model_uri: str = Field(description="新的模型 URI（例如 s3://... 或本地路径）")
    confirm: bool = Field(
        default=False,
        description="必须为 true 才会执行实际 hotswap；false 时仅返回计划",
    )


async def _call_hotswap_model(
    pipeline_name: str,
    node: str,
    model_uri: str,
    *,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Call CP POST /api/control/hotswap to swap model."""

    settings = get_settings()
    base = settings.cp_base_url.rstrip("/")
    url = f"{base}/api/control/hotswap"

    payload = {
        "pipeline_name": pipeline_name,
        "node": node,
        "model_uri": model_uri,
    }

    headers: Dict[str, str] = {}
    if tenant:
        headers["X-Tenant"] = tenant

    async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
        response = await client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = None
    return {"status_code": response.status_code, "payload": body}


@tool("hotswap_model")
async def hotswap_model_tool(
    pipeline_name: str,
    node: str,
    model_uri: str,
    confirm: bool = False,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对指定 pipeline/node 执行模型热切换的高危工具。

    约束：
    - 若 `confirm=false`（默认），仅返回 hotswap 计划，不执行实际操作；
    - 若 `confirm=true`，调用 CP `/api/control/hotswap` 执行模型切换。
    """

    plan = await plan_hotswap_model_tool(
        pipeline_name=pipeline_name,
        node=node,
        model_uri=model_uri,
        tenant=tenant,
    )

    if not confirm:
        return {"mode": "dry-run", "plan": plan}

    result = await _call_hotswap_model(
        pipeline_name=pipeline_name,
        node=node,
        model_uri=model_uri,
        tenant=tenant,
    )
    return {"mode": "execute", "plan": plan, "result": result}


class PlanDrainPipelineInput(BaseModel):
    """Input schema for plan_drain_pipeline tool (dry-run only)."""

    pipeline_name: str = Field(description="目标 pipeline 名称")
    timeout_sec: Optional[int] = Field(
        default=None,
        description="可选 drain 超时时间（秒），缺省则使用后端默认值",
        ge=0,
    )


@tool("plan_drain_pipeline")
async def plan_drain_pipeline_tool(
    pipeline_name: str,
    timeout_sec: Optional[int] = None,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    仅执行 **dry-run** 的 drain 规划工具。

    - 检查 pipeline 是否存在；
    - 查询当前 phase/metrics（若可用）；
    - 返回 drain 计划与建议。
    """

    pipelines = await _fetch_pipelines(tenant=tenant)
    exists = any(pipeline.get("name") == pipeline_name for pipeline in pipelines)

    status = await _fetch_pipeline_status(pipeline_name, tenant=tenant)

    return {
        "pipeline_name": pipeline_name,
        "exists": exists,
        "plan": {
            "action": "drain",
            "timeout_sec": timeout_sec,
        },
        "current_status": status,
    }


class DrainPipelineInput(BaseModel):
    """Input schema for drain_pipeline tool."""

    pipeline_name: str = Field(description="目标 pipeline 名称")
    timeout_sec: Optional[int] = Field(
        default=None,
        description="可选 drain 超时时间（秒），缺省则使用后端默认值",
        ge=0,
    )
    confirm: bool = Field(
        default=False,
        description="必须为 true 才会执行实际 drain；false 时仅返回计划",
    )


async def _call_drain_pipeline(
    pipeline_name: str,
    timeout_sec: Optional[int],
    *,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """Call CP POST /api/control/drain to drain a pipeline."""

    settings = get_settings()
    base = settings.cp_base_url.rstrip("/")
    url = f"{base}/api/control/drain"

    payload: Dict[str, Any] = {"pipeline_name": pipeline_name}
    if timeout_sec is not None:
        payload["timeout_sec"] = timeout_sec

    headers: Dict[str, str] = {}
    if tenant:
        headers["X-Tenant"] = tenant

    async with httpx.AsyncClient(timeout=settings.request_timeout_sec) as client:
        response = await client.post(url, json=payload, headers=headers)
        try:
            body = response.json()
        except Exception:
            body = None
    return {"status_code": response.status_code, "payload": body}


@tool("drain_pipeline")
async def drain_pipeline_tool(
    pipeline_name: str,
    timeout_sec: Optional[int] = None,
    confirm: bool = False,
    tenant: Optional[str] = None,
) -> Dict[str, Any]:
    """
    对指定 pipeline 执行 drain 的高危工具。

    约束：
    - 若 `confirm=false`（默认），仅返回 drain 计划和当前状态，不执行实际 drain；
    - 若 `confirm=true`，调用 CP `/api/control/drain` 执行 drain。
    """

    plan = await plan_drain_pipeline_tool(
        pipeline_name=pipeline_name,
        timeout_sec=timeout_sec,
        tenant=tenant,
    )

    if not confirm:
        return {"mode": "dry-run", "plan": plan}

    result = await _call_drain_pipeline(
        pipeline_name=pipeline_name,
        timeout_sec=timeout_sec,
        tenant=tenant,
    )
    return {"mode": "execute", "plan": plan, "result": result}
