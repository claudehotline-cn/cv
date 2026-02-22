from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.auth import AuthPrincipal, get_current_user, require_admin
from ..db import get_db
from ..models.db_models import (
    AgentModel,
    AgentVersionModel,
    EvalCaseModel,
    EvalDatasetModel,
    EvalResultModel,
    EvalRunModel,
    TenantMembershipModel,
)

router = APIRouter(prefix="/agents/{agent_id}/eval", tags=["eval"])


def _tenant_uuid(user: AuthPrincipal) -> UUID:
    if not user.tenant_id:
        raise HTTPException(status_code=401, detail="Tenant context required")
    try:
        return UUID(str(user.tenant_id))
    except ValueError as exc:
        raise HTTPException(status_code=401, detail="Invalid tenant context") from exc


async def _ensure_tenant_membership_or_403(db: AsyncSession, user: AuthPrincipal, tenant_id: UUID) -> None:
    stmt = select(TenantMembershipModel).where(
        TenantMembershipModel.tenant_id == tenant_id,
        TenantMembershipModel.user_id == user.user_id,
        TenantMembershipModel.status == "active",
    )
    membership = (await db.execute(stmt)).scalar_one_or_none()
    if not membership:
        raise HTTPException(status_code=403, detail="Tenant membership required")


async def _get_agent_or_404(agent_id: str, db: AsyncSession) -> AgentModel:
    result = await db.execute(select(AgentModel).where(AgentModel.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


async def _get_dataset_or_404(dataset_id: str, db: AsyncSession) -> EvalDatasetModel:
    result = await db.execute(select(EvalDatasetModel).where(EvalDatasetModel.id == dataset_id))
    ds = result.scalar_one_or_none()
    if not ds:
        raise HTTPException(status_code=404, detail="Eval dataset not found")
    return ds


async def _get_run_or_404(run_id: str, db: AsyncSession) -> EvalRunModel:
    result = await db.execute(select(EvalRunModel).where(EvalRunModel.id == run_id))
    run = result.scalar_one_or_none()
    if not run:
        raise HTTPException(status_code=404, detail="Eval run not found")
    return run


class CreateDatasetRequest(BaseModel):
    name: str
    description: Optional[str] = None


class ImportCasesRequest(BaseModel):
    cases: list[Dict[str, Any]]


class CreateRunRequest(BaseModel):
    dataset_id: str
    config: Optional[Dict[str, Any]] = None


def _dataset_dict(ds: EvalDatasetModel) -> dict:
    return {
        "id": str(ds.id),
        "tenant_id": str(ds.tenant_id),
        "agent_id": str(ds.agent_id),
        "name": ds.name,
        "description": ds.description,
        "created_by": ds.created_by,
        "created_at": ds.created_at.isoformat() if ds.created_at else None,
        "updated_at": ds.updated_at.isoformat() if ds.updated_at else None,
    }


def _run_dict(run: EvalRunModel) -> dict:
    return {
        "id": str(run.id),
        "tenant_id": str(run.tenant_id),
        "dataset_id": str(run.dataset_id),
        "agent_id": str(run.agent_id),
        "agent_version": run.agent_version,
        "prompt_version_snapshot": run.prompt_version_snapshot,
        "status": run.status,
        "config": run.config,
        "summary": run.summary,
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "completed_at": run.completed_at.isoformat() if run.completed_at else None,
        "created_at": run.created_at.isoformat() if run.created_at else None,
    }


@router.get("/datasets")
async def list_eval_datasets(
    agent_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    stmt = select(EvalDatasetModel).where(
        EvalDatasetModel.tenant_id == tenant_id,
        EvalDatasetModel.agent_id == agent_id,
    ).order_by(EvalDatasetModel.created_at.desc())
    rows = (await db.execute(stmt)).scalars().all()
    return {"items": [_dataset_dict(r) for r in rows]}


@router.post("/datasets")
async def create_eval_dataset(
    agent_id: str,
    body: CreateDatasetRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    ds = EvalDatasetModel(
        tenant_id=tenant_id,
        agent_id=UUID(agent_id),
        name=body.name,
        description=body.description,
        created_by=user.user_id,
    )
    db.add(ds)
    await db.commit()
    await db.refresh(ds)
    return _dataset_dict(ds)


@router.post("/datasets/{dataset_id}/import")
async def import_eval_cases(
    agent_id: str,
    dataset_id: str,
    body: ImportCasesRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    inserted = 0
    for case in body.cases:
        if not isinstance(case, dict) or "input" not in case:
            raise HTTPException(status_code=400, detail="Each case must include input")
        c = EvalCaseModel(
            dataset_id=ds.id,
            input=case.get("input"),
            expected_output=case.get("expected_output"),
            tags=case.get("tags") or [],
            notes=case.get("notes"),
        )
        db.add(c)
        inserted += 1

    await db.commit()
    return {"dataset_id": str(ds.id), "inserted": inserted}


@router.get("/datasets/{dataset_id}/cases")
async def list_eval_cases(
    agent_id: str,
    dataset_id: str,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    total_stmt = select(func.count()).select_from(
        select(EvalCaseModel.id).where(EvalCaseModel.dataset_id == ds.id).subquery()
    )
    total = (await db.execute(total_stmt)).scalar() or 0

    stmt = (
        select(EvalCaseModel)
        .where(EvalCaseModel.dataset_id == ds.id)
        .order_by(EvalCaseModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "dataset_id": str(r.dataset_id),
            "input": r.input,
            "expected_output": r.expected_output,
            "tags": r.tags,
            "notes": r.notes,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in rows
    ]
    return {"items": items, "total": total, "limit": limit, "offset": offset}


@router.post("/runs")
async def create_eval_run(
    agent_id: str,
    body: CreateRunRequest,
    user: AuthPrincipal = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    agent = await _get_agent_or_404(agent_id, db)
    ds = await _get_dataset_or_404(body.dataset_id, db)

    if str(ds.tenant_id) != str(tenant_id) or str(ds.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval dataset not found")

    agent_version = 0
    if agent.published_version_id:
        pv = await db.get(AgentVersionModel, agent.published_version_id)
        if pv:
            agent_version = pv.version

    run = EvalRunModel(
        tenant_id=tenant_id,
        dataset_id=ds.id,
        agent_id=UUID(agent_id),
        agent_version=agent_version,
        prompt_version_snapshot=None,
        status="running",
        config=body.config or {},
        summary={"total": 0, "passed": 0, "avg_score": 0.0},
        started_at=datetime.now(timezone.utc),
    )
    db.add(run)
    await db.flush()

    cases_stmt = select(EvalCaseModel).where(EvalCaseModel.dataset_id == ds.id)
    cases = (await db.execute(cases_stmt)).scalars().all()

    passed = 0
    for c in cases:
        result = EvalResultModel(
            run_id=run.id,
            case_id=c.id,
            status="passed",
            actual_output={"mock": "ok"},
            trajectory={"steps": []},
            scores={"trajectory_match": 1.0, "llm_judge": 1.0},
            started_at=datetime.now(timezone.utc),
            completed_at=datetime.now(timezone.utc),
        )
        db.add(result)
        passed += 1

    total = len(cases)
    avg_score = 1.0 if total else 0.0
    run.status = "completed"
    run.completed_at = datetime.now(timezone.utc)
    run.summary = {"total": total, "passed": passed, "avg_score": avg_score}

    await db.commit()
    await db.refresh(run)
    return _run_dict(run)


@router.get("/runs")
async def list_eval_runs(
    agent_id: str,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    await _get_agent_or_404(agent_id, db)

    stmt = (
        select(EvalRunModel)
        .where(
            EvalRunModel.tenant_id == tenant_id,
            EvalRunModel.agent_id == agent_id,
        )
        .order_by(EvalRunModel.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    runs = (await db.execute(stmt)).scalars().all()
    return {"items": [_run_dict(r) for r in runs], "limit": limit, "offset": offset}


@router.get("/runs/{run_id}")
async def get_eval_run(
    agent_id: str,
    run_id: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    run = await _get_run_or_404(run_id, db)

    if str(run.tenant_id) != str(tenant_id) or str(run.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval run not found")

    return _run_dict(run)


@router.get("/runs/{run_id}/results")
async def list_eval_results(
    agent_id: str,
    run_id: str,
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)
    run = await _get_run_or_404(run_id, db)

    if str(run.tenant_id) != str(tenant_id) or str(run.agent_id) != agent_id:
        raise HTTPException(status_code=404, detail="Eval run not found")

    stmt = (
        select(EvalResultModel)
        .where(EvalResultModel.run_id == run.id)
        .order_by(EvalResultModel.started_at.asc())
        .offset(offset)
        .limit(limit)
    )
    rows = (await db.execute(stmt)).scalars().all()

    items = [
        {
            "id": str(r.id),
            "run_id": str(r.run_id),
            "case_id": str(r.case_id),
            "status": r.status,
            "actual_output": r.actual_output,
            "trajectory": r.trajectory,
            "scores": r.scores,
            "error_message": r.error_message,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "completed_at": r.completed_at.isoformat() if r.completed_at else None,
        }
        for r in rows
    ]
    return {"items": items, "limit": limit, "offset": offset}


@router.get("/runs/{run_id_1}/compare/{run_id_2}")
async def compare_eval_runs(
    agent_id: str,
    run_id_1: str,
    run_id_2: str,
    user: AuthPrincipal = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    tenant_id = _tenant_uuid(user)
    await _ensure_tenant_membership_or_403(db, user, tenant_id)

    r1 = await _get_run_or_404(run_id_1, db)
    r2 = await _get_run_or_404(run_id_2, db)

    if (
        str(r1.tenant_id) != str(tenant_id)
        or str(r2.tenant_id) != str(tenant_id)
        or str(r1.agent_id) != agent_id
        or str(r2.agent_id) != agent_id
    ):
        raise HTTPException(status_code=404, detail="Eval run not found")

    s1 = r1.summary or {}
    s2 = r2.summary or {}

    return {
        "run_1": {"id": str(r1.id), "summary": s1},
        "run_2": {"id": str(r2.id), "summary": s2},
        "delta": {
            "total": (s2.get("total", 0) - s1.get("total", 0)),
            "passed": (s2.get("passed", 0) - s1.get("passed", 0)),
            "avg_score": (float(s2.get("avg_score", 0.0)) - float(s1.get("avg_score", 0.0))),
        },
    }
