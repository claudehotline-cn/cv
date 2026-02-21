import logging
import os
import uuid
import asyncio
import json
from typing import Any, Dict, Optional

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, Body
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agent_core.events import AuditEmitter
from agent_core.settings import get_settings

from ..db import get_db
from ..models.db_models import TenantMembershipModel


def _is_strict_auth_mode() -> bool:
    return (os.getenv("AUTH_MODE") or "mixed").strip().lower() == "strict"


def _allow_dev_headers() -> bool:
    return (os.getenv("AUTH_ALLOW_DEV_HEADERS") or "true").strip().lower() in ("1", "true", "yes", "on")


_LOGGER = logging.getLogger(__name__)
settings = get_settings()


def _rag_base_url() -> str:
    # Inside docker-compose network, rag-service is reachable by container name.
    return (os.getenv("RAG_SERVICE_URL") or "http://rag-service:8200").rstrip("/")


def _dev_user_ctx(req: Request) -> Dict[str, str]:
    cached = getattr(req.state, "rag_user_ctx", None)
    if isinstance(cached, dict):
        return cached

    auth_header = (req.headers.get("Authorization") or "").strip()
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ", 1)[1].strip()
        if token:
            introspect_url = (os.getenv("AUTH_INTROSPECTION_URL") or "http://agent-auth:8000/internal/introspect").strip()
            try:
                with httpx.Client(timeout=10) as client:
                    resp = client.post(introspect_url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code < 400:
                    data = resp.json()
                    if data.get("active"):
                        user_id = str(data.get("sub") or "anonymous").strip() or "anonymous"
                        role = str(data.get("role") or "user").strip().lower() or "user"
                        if role not in ("admin", "user"):
                            role = "user"
                        tenant_id = str(data.get("tenant_id") or settings.auth_default_tenant_id).strip() or settings.auth_default_tenant_id
                        tenant_role = str(data.get("tenant_role") or ("owner" if role == "admin" else "member")).strip().lower()
                        if tenant_role not in ("owner", "admin", "member"):
                            tenant_role = "member"

                        requested_tenant_id = (req.headers.get("X-Tenant-Id") or "").strip()
                        if requested_tenant_id:
                            try:
                                uuid.UUID(requested_tenant_id)
                                tenant_id = requested_tenant_id
                                requested_tenant_role = (req.headers.get("X-Tenant-Role") or tenant_role).strip().lower()
                                if requested_tenant_role in ("owner", "admin", "member"):
                                    tenant_role = requested_tenant_role
                            except ValueError:
                                pass

                        ctx = {
                            "user_id": user_id,
                            "role": role,
                            "tenant_id": tenant_id,
                            "tenant_role": tenant_role,
                        }
                        req.state.rag_user_ctx = ctx
                        return ctx
            except Exception:
                _LOGGER.exception("Failed to introspect bearer token for rag auth")

    if _is_strict_auth_mode() or not _allow_dev_headers():
        ctx = {
            "user_id": "anonymous",
            "role": "user",
            "tenant_id": settings.auth_default_tenant_id,
            "tenant_role": "member",
        }
        req.state.rag_user_ctx = ctx
        return ctx

    user_id = (req.headers.get("X-User-Id") or "anonymous").strip() or "anonymous"
    role = (req.headers.get("X-User-Role") or "user").strip().lower()
    if role not in ("admin", "user"):
        role = "user"
    tenant_id = (req.headers.get("X-Tenant-Id") or settings.auth_default_tenant_id).strip() or settings.auth_default_tenant_id
    tenant_role = (req.headers.get("X-Tenant-Role") or ("owner" if role == "admin" else "member")).strip().lower()
    if tenant_role not in ("owner", "admin", "member"):
        tenant_role = "member"
    ctx = {
        "user_id": user_id,
        "role": role,
        "tenant_id": tenant_id,
        "tenant_role": tenant_role,
    }
    req.state.rag_user_ctx = ctx
    return ctx


def _require_authenticated(ctx: Dict[str, str]) -> None:
    if not (ctx.get("user_id") or "").strip() or ctx.get("user_id") == "anonymous":
        raise HTTPException(status_code=401, detail="Authentication required")


def _require_admin(ctx: Dict[str, str]) -> None:
    _require_authenticated(ctx)
    if ctx.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")


def _require_tenant_context(ctx: Dict[str, str]) -> None:
    tenant_id = (ctx.get("tenant_id") or "").strip()
    if not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        uuid.UUID(tenant_id)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


async def _require_tenant_membership(req: Request, db: AsyncSession = Depends(get_db)) -> None:
    ctx = _dev_user_ctx(req)
    _require_authenticated(ctx)
    _require_tenant_context(ctx)

    user_id = (ctx.get("user_id") or "").strip()
    tenant_id = (ctx.get("tenant_id") or "").strip()
    if not user_id or not tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")

    membership = await db.scalar(
        select(TenantMembershipModel).where(
            TenantMembershipModel.user_id == user_id,
            TenantMembershipModel.tenant_id == uuid.UUID(tenant_id),
            TenantMembershipModel.status == "active",
        )
    )
    if membership is None:
        raise HTTPException(status_code=403, detail="Tenant membership required")


async def _require_rag_authenticated(req: Request) -> None:
    ctx = _dev_user_ctx(req)
    _require_authenticated(ctx)
    _require_tenant_context(ctx)


router = APIRouter(
    prefix="/rag",
    tags=["rag"],
    dependencies=[Depends(_require_rag_authenticated), Depends(_require_tenant_membership)],
)


def _request_id(req: Request) -> str:
    raw = (req.headers.get("X-Request-Id") or "").strip()
    if raw:
        try:
            return str(uuid.UUID(raw))
        except Exception:
            pass
    return str(uuid.uuid4())


async def _emit_audit(
    *,
    req: Request,
    ctx: Dict[str, str],
    event_type: str,
    request_id: str,
    span_id: Optional[str],
    payload: Dict[str, Any],
):
    try:
        event_bus = req.app.state.event_bus
        emitter = AuditEmitter(redis=event_bus.redis)
        payload_with_tenant = {
            **payload,
            "tenant_id": ctx.get("tenant_id") or settings.auth_default_tenant_id,
        }
        await emitter.emit(
            event_type=event_type,
            request_id=request_id,
            span_id=span_id,
            component="rag",
            actor_type="user",
            actor_id=ctx.get("user_id", "anonymous"),
            payload=payload_with_tenant,
        )
    except Exception:
        _LOGGER.exception("Failed to emit rag audit event")


async def _proxy_json(
    *,
    method: str,
    path: str,
    req: Request,
    request_id: Optional[str] = None,
    json_body: Any = None,
    params: Optional[Dict[str, Any]] = None,
):
    url = _rag_base_url() + path
    ctx = _dev_user_ctx(req)
    headers: Dict[str, str] = {}
    auth_header = (req.headers.get("Authorization") or "").strip()
    if auth_header:
        headers["Authorization"] = auth_header
    if request_id:
        headers["X-Request-Id"] = request_id
    headers["X-User-Id"] = ctx.get("user_id", "anonymous")
    headers["X-User-Role"] = ctx.get("role", "user")
    headers["X-Tenant-Id"] = ctx.get("tenant_id") or settings.auth_default_tenant_id
    if ctx.get("tenant_role"):
        headers["X-Tenant-Role"] = ctx["tenant_role"]

    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.request(method, url, json=json_body, params=params, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


async def _proxy_multipart(
    *,
    path: str,
    req: Request,
    request_id: str,
    file: UploadFile,
):
    url = _rag_base_url() + path
    ctx = _dev_user_ctx(req)
    headers = {
        "X-Request-Id": request_id,
        "X-User-Id": ctx.get("user_id", "anonymous"),
        "X-User-Role": ctx.get("role", "user"),
        "X-Tenant-Id": ctx.get("tenant_id") or settings.auth_default_tenant_id,
    }
    auth_header = (req.headers.get("Authorization") or "").strip()
    if auth_header:
        headers["Authorization"] = auth_header
    if ctx.get("tenant_role"):
        headers["X-Tenant-Role"] = ctx["tenant_role"]

    data = await file.read()
    files = {"file": (file.filename, data, file.content_type or "application/octet-stream")}
    async with httpx.AsyncClient(timeout=600) as client:
        r = await client.post(url, files=files, headers=headers)
        if r.status_code >= 400:
            raise HTTPException(status_code=r.status_code, detail=r.text)
        return r.json()


@router.get("/knowledge-bases")
async def list_knowledge_bases(req: Request):
    return await _proxy_json(method="GET", path="/api/knowledge-bases", req=req)


@router.post("/knowledge-bases")
async def create_knowledge_base(req: Request, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_create", "input": body},
    )
    try:
        out = await _proxy_json(method="POST", path="/api/knowledge-bases", req=req, json_body=body)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "kb_create", "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_create", "result": out},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}")
async def get_knowledge_base(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}", req=req)


@router.put("/knowledge-bases/{kb_id}")
async def update_knowledge_base(req: Request, kb_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_update", "kb_id": kb_id, "input": body},
    )
    try:
        out = await _proxy_json(method="PUT", path=f"/api/knowledge-bases/{kb_id}", req=req, json_body=body)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "kb_update", "kb_id": kb_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_update", "kb_id": kb_id, "result": out},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.delete("/knowledge-bases/{kb_id}")
async def delete_knowledge_base(req: Request, kb_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_delete", "kb_id": kb_id},
    )
    try:
        out = await _proxy_json(method="DELETE", path=f"/api/knowledge-bases/{kb_id}", req=req)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "kb_delete", "kb_id": kb_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "kb_delete", "kb_id": kb_id, "result": out},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/stats")
async def get_kb_stats(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/stats", req=req)


@router.get("/knowledge-bases/{kb_id}/documents")
async def list_documents(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/documents", req=req)


@router.post("/knowledge-bases/{kb_id}/documents/upload")
async def upload_document(req: Request, kb_id: int, file: UploadFile = File(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "doc_upload", "kb_id": kb_id, "filename": file.filename, "queue": "rag:queue"},
    )
    try:
        out = await _proxy_multipart(path=f"/api/knowledge-bases/{kb_id}/documents/upload", req=req, request_id=rid, file=file)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/documents/import-url")
async def import_url(req: Request, kb_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "doc_import_url", "kb_id": kb_id, "queue": "rag:queue", "input": body},
    )

    # rag-service expects URLImportRequest {url, knowledge_base_id}
    if "knowledge_base_id" not in body:
        body = {**body, "knowledge_base_id": kb_id}

    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/documents/import-url",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/reindex")
async def reindex_document(req: Request, kb_id: int, doc_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "doc_reindex", "kb_id": kb_id, "doc_id": doc_id, "queue": "rag:queue"},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/reindex",
            req=req,
            request_id=rid,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/chunks")
async def list_document_chunks(
    req: Request,
    kb_id: int,
    doc_id: int,
    offset: int = 0,
    limit: int = 50,
    include_parents: bool = True,
):
    return await _proxy_json(
        method="GET",
        path=f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/chunks",
        req=req,
        params={"offset": offset, "limit": limit, "include_parents": include_parents},
    )


@router.get("/knowledge-bases/{kb_id}/documents/{doc_id}/outline")
async def get_document_outline(req: Request, kb_id: int, doc_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/outline", req=req)


@router.delete("/knowledge-bases/{kb_id}/documents/{doc_id}")
async def delete_document(req: Request, kb_id: int, doc_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "doc_delete", "kb_id": kb_id, "doc_id": doc_id},
    )

    try:
        out = await _proxy_json(method="DELETE", path=f"/api/documents/{doc_id}", req=req, request_id=rid)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "doc_delete", "kb_id": kb_id, "doc_id": doc_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "doc_delete", "kb_id": kb_id, "doc_id": doc_id, "result": out},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )

    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/documents/{doc_id}/preview-chunks")
async def preview_document_chunks(req: Request, kb_id: int, doc_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "preview_chunks", "kb_id": kb_id, "doc_id": doc_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/documents/{doc_id}/preview-chunks",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "preview_chunks", "kb_id": kb_id, "doc_id": doc_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "preview_chunks", "kb_id": kb_id, "doc_id": doc_id},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    return out


@router.post("/knowledge-bases/{kb_id}/rebuild-vectors")
async def rebuild_vectors(req: Request, kb_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "rebuild_vectors", "kb_id": kb_id, "queue": "rag:queue"},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/rebuild-vectors",
            req=req,
            request_id=rid,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/build-graph")
async def build_graph(req: Request, kb_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "build_graph", "kb_id": kb_id, "queue": "rag:queue"},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/build-graph",
            req=req,
            request_id=rid,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/retrieve")
async def retrieve(req: Request, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "retrieve", "input": body},
    )

    try:
        out = await _proxy_json(method="POST", path="/api/retrieve", req=req, request_id=rid, json_body=body)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "retrieve", "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "retrieve"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/graph/retrieve")
async def graph_retrieve(req: Request, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "graph_retrieve", "input": body},
    )

    try:
        out = await _proxy_json(method="POST", path="/api/graph/retrieve", req=req, request_id=rid, json_body=body)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "graph_retrieve", "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "graph_retrieve"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/evaluate")
async def evaluate(req: Request, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "evaluate", "input": {k: body.get(k) for k in ("question", "answer") if k in body}},
    )

    try:
        out = await _proxy_json(method="POST", path="/api/evaluate", req=req, request_id=rid, json_body=body)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "evaluate", "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "evaluate"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


# ==================== RAG Eval / Benchmarks ====================


@router.get("/knowledge-bases/{kb_id}/eval/datasets")
async def list_eval_datasets(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/datasets", req=req)


@router.get("/knowledge-bases/{kb_id}/eval/datasets/export")
async def export_all_eval_datasets(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/datasets/export", req=req)


@router.post("/knowledge-bases/{kb_id}/eval/datasets")
async def create_eval_dataset(req: Request, kb_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)
    body = {**body, "created_by": ctx.get("user_id")}

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_create", "kb_id": kb_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_dataset_create", "kb_id": kb_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_create", "kb_id": kb_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
async def get_eval_dataset(req: Request, kb_id: int, dataset_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}", req=req)


@router.put("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
async def update_eval_dataset(req: Request, kb_id: int, dataset_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_update", "kb_id": kb_id, "dataset_id": dataset_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="PUT",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={
                "action": "eval_dataset_update",
                "kb_id": kb_id,
                "dataset_id": dataset_id,
                "error_message": str(e),
            },
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_update", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.delete("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
async def delete_eval_dataset(req: Request, kb_id: int, dataset_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_delete", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    try:
        out = await _proxy_json(
            method="DELETE",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}",
            req=req,
            request_id=rid,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_dataset_delete", "kb_id": kb_id, "dataset_id": dataset_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_delete", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases")
async def list_eval_cases(req: Request, kb_id: int, dataset_id: int):
    allowed = {"q", "tag", "offset", "limit"}
    params = {k: v for (k, v) in req.query_params.items() if k in allowed}
    return await _proxy_json(
        method="GET",
        path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases",
        req=req,
        params=params,
    )


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases")
async def create_eval_case(req: Request, kb_id: int, dataset_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_create", "kb_id": kb_id, "dataset_id": dataset_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_case_create", "kb_id": kb_id, "dataset_id": dataset_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_create", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases/bulk-delete")
async def bulk_delete_eval_cases(req: Request, kb_id: int, dataset_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={
            "action": "eval_cases_bulk_delete",
            "kb_id": kb_id,
            "dataset_id": dataset_id,
            "input": body,
        },
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases/bulk-delete",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={
                "action": "eval_cases_bulk_delete",
                "kb_id": kb_id,
                "dataset_id": dataset_id,
                "error_message": str(e),
            },
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_cases_bulk_delete", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.put("/eval/cases/{case_id}")
async def update_eval_case(req: Request, case_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_update", "case_id": case_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="PUT",
            path=f"/api/eval/cases/{case_id}",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_case_update", "case_id": case_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_update", "case_id": case_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.delete("/eval/cases/{case_id}")
async def delete_eval_case(req: Request, case_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_delete", "case_id": case_id},
    )
    try:
        out = await _proxy_json(method="DELETE", path=f"/api/eval/cases/{case_id}", req=req, request_id=rid)
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_case_delete", "case_id": case_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_case_delete", "case_id": case_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/import")
async def import_eval_dataset(req: Request, kb_id: int, dataset_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_import", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/import",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "eval_dataset_import", "kb_id": kb_id, "dataset_id": dataset_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "eval_dataset_import", "kb_id": kb_id, "dataset_id": dataset_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/export")
async def export_eval_dataset(req: Request, kb_id: int, dataset_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/export", req=req)


@router.post("/knowledge-bases/{kb_id}/eval/benchmarks/runs")
async def create_benchmark_run(req: Request, kb_id: int, body: Dict[str, Any] = Body(...)):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)
    body = {**body, "created_by": ctx.get("user_id")}

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_requested",
        request_id=rid,
        span_id=rid,
        payload={"action": "benchmark_run_create", "kb_id": kb_id, "input": body},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs",
            req=req,
            request_id=rid,
            json_body=body,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="tool_val_failed",
            request_id=rid,
            span_id=rid,
            payload={"action": "benchmark_run_create", "kb_id": kb_id, "error_message": str(e)},
        )
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="tool_call_executed",
        request_id=rid,
        span_id=rid,
        payload={"action": "benchmark_run_create", "kb_id": kb_id},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_finished",
        request_id=rid,
        span_id=None,
        payload={},
    )
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs")
async def list_benchmark_runs(req: Request, kb_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs", req=req)


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}")
async def get_benchmark_run(req: Request, kb_id: int, run_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}", req=req)


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/results")
async def list_benchmark_results(req: Request, kb_id: int, run_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/results", req=req)


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/stream")
async def stream_benchmark_run(req: Request, kb_id: int, run_id: int):
    """SSE: stream benchmark run progress without polling."""

    async def event_generator():
        from agent_core.events import RedisEventBus

        event_bus = RedisEventBus(settings.redis_url)
        stream_key = f"rag:benchmark_run:{int(run_id)}:stream"
        try:
            async for event in event_bus.subscribe(stream_key):
                yield f"data: {json.dumps(event)}\n\n"
                if await req.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/export")
async def export_benchmark_run(req: Request, kb_id: int, run_id: int):
    return await _proxy_json(method="GET", path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/export", req=req)


@router.post("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/execute")
async def execute_benchmark(req: Request, kb_id: int, run_id: int):
    ctx = _dev_user_ctx(req)
    _require_admin(ctx)
    rid = _request_id(req)

    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="run_started",
        request_id=rid,
        span_id=None,
        payload={"root_agent_name": "rag"},
    )
    await _emit_audit(
        req=req,
        ctx=ctx,
        event_type="job_queued",
        request_id=rid,
        span_id=rid,
        payload={"action": "benchmark_execute", "kb_id": kb_id, "run_id": run_id, "queue": "rag:queue"},
    )
    try:
        out = await _proxy_json(
            method="POST",
            path=f"/api/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/execute",
            req=req,
            request_id=rid,
        )
    except Exception as e:
        await _emit_audit(
            req=req,
            ctx=ctx,
            event_type="run_failed",
            request_id=rid,
            span_id=None,
            payload={"error_message": str(e)},
        )
        raise
    if isinstance(out, dict):
        out.setdefault("request_id", rid)
    return out
