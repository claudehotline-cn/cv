from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import get_db
from ..models.db_models import PromptTemplateModel, PromptVersionModel
from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..core.prompt_resolver import preview_render

router = APIRouter(prefix="/prompts", tags=["prompts"], redirect_slashes=False)


# --- Pydantic models ---

class PromptTemplateCreate(BaseModel):
    key: str
    name: str
    description: Optional[str] = None
    category: Optional[str] = None
    content: Optional[str] = None
    variables_schema: Optional[Dict[str, Any]] = None


class PromptTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    category: Optional[str] = None


class CreateDraftRequest(BaseModel):
    content: str
    variables_schema: Optional[Dict[str, Any]] = None
    change_summary: Optional[str] = None
    base_version: Optional[int] = None


class UpdateDraftRequest(BaseModel):
    content: Optional[str] = None
    variables_schema: Optional[Dict[str, Any]] = None
    change_summary: Optional[str] = None


class PreviewRequest(BaseModel):
    content: Optional[str] = None
    variables: Optional[Dict[str, str]] = None
    version: Optional[int] = None


# --- Helpers ---

def _template_dict(t: PromptTemplateModel) -> dict:
    return {
        "id": str(t.id),
        "tenant_id": str(t.tenant_id) if t.tenant_id else None,
        "key": t.key,
        "name": t.name,
        "description": t.description,
        "category": t.category,
        "created_by": t.created_by,
        "created_at": t.created_at.isoformat() if t.created_at else None,
        "updated_at": t.updated_at.isoformat() if t.updated_at else None,
    }


def _version_dict(v: PromptVersionModel) -> dict:
    return {
        "id": str(v.id),
        "template_id": str(v.template_id),
        "version": v.version,
        "status": v.status,
        "content": v.content,
        "variables_schema": v.variables_schema,
        "change_summary": v.change_summary,
        "created_by": v.created_by,
        "created_at": v.created_at.isoformat() if v.created_at else None,
        "published_at": v.published_at.isoformat() if v.published_at else None,
    }


async def _get_template_or_404(template_id: str, db: AsyncSession) -> PromptTemplateModel:
    result = await db.execute(select(PromptTemplateModel).where(PromptTemplateModel.id == template_id))
    tmpl = result.scalar_one_or_none()
    if not tmpl:
        raise HTTPException(status_code=404, detail="Prompt template not found")
    return tmpl


async def _get_version_or_404(template_id: str, version: int, db: AsyncSession) -> PromptVersionModel:
    result = await db.execute(
        select(PromptVersionModel).where(
            PromptVersionModel.template_id == template_id,
            PromptVersionModel.version == version,
        )
    )
    ver = result.scalar_one_or_none()
    if not ver:
        raise HTTPException(status_code=404, detail="Version not found")
    return ver


async def _next_version(template_id, db: AsyncSession) -> int:
    result = await db.execute(
        select(func.coalesce(func.max(PromptVersionModel.version), 0))
        .where(PromptVersionModel.template_id == template_id)
    )
    return result.scalar() + 1


async def _version_summary(version_id, db: AsyncSession) -> Optional[dict]:
    if not version_id:
        return None
    ver = await db.get(PromptVersionModel, version_id)
    if not ver:
        return None
    return {"version": ver.version, "status": ver.status, "published_at": ver.published_at.isoformat() if ver.published_at else None}


# --- 1. List templates ---

@router.get("")
async def list_prompts(
    category: Optional[str] = Query(None),
    key: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(PromptTemplateModel)
    if category:
        stmt = stmt.where(PromptTemplateModel.category == category)
    if key:
        stmt = stmt.where(PromptTemplateModel.key.ilike(f"%{key}%"))
    total_result = await db.execute(select(func.count()).select_from(stmt.subquery()))
    total = total_result.scalar()
    stmt = stmt.order_by(PromptTemplateModel.created_at.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    templates = result.scalars().all()
    items = []
    for t in templates:
        d = _template_dict(t)
        d["published_version"] = await _version_summary(t.published_version_id, db)
        d["draft_version"] = await _version_summary(t.draft_version_id, db)
        items.append(d)
    return {"items": items, "total": total, "limit": limit, "offset": offset}


# --- 2. Get template detail ---

@router.get("/{template_id}")
async def get_prompt(
    template_id: str,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    d = _template_dict(tmpl)
    d["published_version"] = await _version_summary(tmpl.published_version_id, db)
    d["draft_version"] = await _version_summary(tmpl.draft_version_id, db)
    return d


# --- 3. Create custom template ---

@router.post("")
async def create_prompt(
    body: PromptTemplateCreate,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = PromptTemplateModel(
        key=body.key,
        name=body.name,
        description=body.description,
        category=body.category,
        created_by=user.user_id,
    )
    db.add(tmpl)
    await db.flush()

    if body.content:
        ver = PromptVersionModel(
            template_id=tmpl.id,
            version=1,
            status="published",
            content=body.content,
            variables_schema=body.variables_schema,
            change_summary="Initial version",
            created_by=user.user_id,
            published_at=datetime.now(timezone.utc),
        )
        db.add(ver)
        await db.flush()
        tmpl.published_version_id = ver.id

    await db.commit()
    await db.refresh(tmpl)
    return _template_dict(tmpl)


# --- 4. Update template meta ---

@router.put("/{template_id}")
async def update_prompt(
    template_id: str,
    body: PromptTemplateUpdate,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    if body.name is not None:
        tmpl.name = body.name
    if body.description is not None:
        tmpl.description = body.description
    if body.category is not None:
        tmpl.category = body.category
    await db.commit()
    await db.refresh(tmpl)
    return _template_dict(tmpl)


# --- 5. List versions ---

@router.get("/{template_id}/versions")
async def list_versions(
    template_id: str,
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await _get_template_or_404(template_id, db)
    stmt = select(PromptVersionModel).where(PromptVersionModel.template_id == template_id)
    if status:
        stmt = stmt.where(PromptVersionModel.status == status)
    stmt = stmt.order_by(PromptVersionModel.version.desc()).offset(offset).limit(limit)
    result = await db.execute(stmt)
    return [_version_dict(v) for v in result.scalars().all()]


# --- 6. Create draft ---

@router.post("/{template_id}/versions")
async def create_draft(
    template_id: str,
    body: CreateDraftRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    content = body.content
    variables_schema = body.variables_schema

    if body.base_version is not None:
        base = await _get_version_or_404(template_id, body.base_version, db)
        if not content:
            content = base.content
        if variables_schema is None:
            variables_schema = base.variables_schema

    next_ver = await _next_version(template_id, db)
    ver = PromptVersionModel(
        template_id=tmpl.id,
        version=next_ver,
        status="draft",
        content=content,
        variables_schema=variables_schema,
        change_summary=body.change_summary,
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    tmpl.draft_version_id = ver.id
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 7. Update draft ---

@router.put("/{template_id}/versions/{version}")
async def update_draft(
    template_id: str,
    version: int,
    body: UpdateDraftRequest,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    await _get_template_or_404(template_id, db)
    ver = await _get_version_or_404(template_id, version, db)
    if ver.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft versions can be edited")
    if body.content is not None:
        ver.content = body.content
    if body.variables_schema is not None:
        ver.variables_schema = body.variables_schema
    if body.change_summary is not None:
        ver.change_summary = body.change_summary
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 8. Publish draft ---

@router.post("/{template_id}/versions/{version}/publish")
async def publish_version(
    template_id: str,
    version: int,
    _: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    ver = await _get_version_or_404(template_id, version, db)
    if ver.status != "draft":
        raise HTTPException(status_code=400, detail="Only draft versions can be published")

    if tmpl.published_version_id:
        old_pub = await db.get(PromptVersionModel, tmpl.published_version_id)
        if old_pub and old_pub.status == "published":
            old_pub.status = "archived"

    ver.status = "published"
    ver.published_at = datetime.now(timezone.utc)
    tmpl.published_version_id = ver.id
    if tmpl.draft_version_id == ver.id:
        tmpl.draft_version_id = None
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 9. Rollback ---

@router.post("/{template_id}/versions/{version}/rollback")
async def rollback_version(
    template_id: str,
    version: int,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    source = await _get_version_or_404(template_id, version, db)

    next_ver = await _next_version(template_id, db)
    ver = PromptVersionModel(
        template_id=tmpl.id,
        version=next_ver,
        status="draft",
        content=source.content,
        variables_schema=source.variables_schema,
        change_summary=f"Rollback from v{source.version}",
        created_by=user.user_id,
    )
    db.add(ver)
    await db.flush()
    tmpl.draft_version_id = ver.id
    await db.commit()
    await db.refresh(ver)
    return _version_dict(ver)


# --- 10. Preview render ---

@router.post("/{template_id}/preview")
async def preview_prompt(
    template_id: str,
    body: PreviewRequest,
    _: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tmpl = await _get_template_or_404(template_id, db)
    content = body.content

    if content is None:
        if body.version is not None:
            ver = await _get_version_or_404(template_id, body.version, db)
            content = ver.content
        elif tmpl.published_version_id:
            ver = await db.get(PromptVersionModel, tmpl.published_version_id)
            content = ver.content if ver else ""
        else:
            content = ""

    rendered = await preview_render(content, body.variables)
    return {"rendered": rendered, "original": content}
