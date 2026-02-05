"""RAG evaluation datasets and benchmark APIs."""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from ..config import settings
from ..database import get_mysql_db
from ..models import (
    BenchmarkCaseResult,
    BenchmarkQaResult,
    BenchmarkRun,
    EvalCase,
    EvalCaseExpectation,
    EvalDataset,
    KnowledgeBase,
)
from ..queue import enqueue_job

logger = logging.getLogger(__name__)

router = APIRouter()


def _get_request_id_from_headers(req: Request) -> str | None:
    raw = (req.headers.get("X-Request-Id") or "").strip()
    if not raw:
        return None
    try:
        import uuid

        return str(uuid.UUID(raw))
    except Exception:
        return None


async def _schedule_job(
    background_tasks: BackgroundTasks,
    queue_function: str,
    fallback,
    request_id: str | None,
    *args,
):
    if settings.use_job_queue:
        try:
            return await enqueue_job(queue_function, *args, job_id=request_id)
        except Exception as e:
            logger.warning("Failed to enqueue job %s, falling back to BackgroundTasks: %s", queue_function, e)

    background_tasks.add_task(fallback, *args)
    return None


class EvalDatasetCreate(BaseModel):
    name: str
    description: Optional[str] = None
    created_by: Optional[str] = None


class EvalDatasetUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None


class EvalCaseCreate(BaseModel):
    query: str
    expected_sources: List[str] = []
    expected_answer: Optional[str] = None
    notes: Optional[str] = None
    tags: List[str] = []


class EvalCaseUpdate(BaseModel):
    query: Optional[str] = None
    expected_sources: Optional[List[str]] = None
    expected_answer: Optional[str] = None
    notes: Optional[str] = None
    tags: Optional[List[str]] = None


def _case_out(case: EvalCase, expected_answer: str | None) -> dict:
    d = case.to_dict()
    d["expected_answer"] = expected_answer
    return d


class EvalDatasetImport(BaseModel):
    replace: bool = False
    cases: List[EvalCaseCreate] = []


class BenchmarkRunCreate(BaseModel):
    dataset_id: int
    mode: str  # vector|graph|qa
    top_k: int = 5
    created_by: Optional[str] = None


@router.get("/knowledge-bases/{kb_id}/eval/datasets")
def list_eval_datasets(kb_id: int, db: Session = Depends(get_mysql_db)):
    kbs = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, KnowledgeBase.is_active == True).first()
    if not kbs:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    items = (
        db.query(EvalDataset)
        .filter(EvalDataset.knowledge_base_id == kb_id, EvalDataset.is_active == True)
        .order_by(EvalDataset.updated_at.desc())
        .all()
    )
    out = []
    for d in items:
        dd = d.to_dict()
        dd["cases_count"] = db.query(EvalCase).filter(EvalCase.dataset_id == d.id).count()
        out.append(dd)
    return {"items": out}


@router.post("/knowledge-bases/{kb_id}/eval/datasets")
def create_eval_dataset(kb_id: int, data: EvalDatasetCreate, db: Session = Depends(get_mysql_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, KnowledgeBase.is_active == True).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    name = (data.name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="name is required")

    exists = (
        db.query(EvalDataset)
        .filter(EvalDataset.knowledge_base_id == kb_id, EvalDataset.name == name, EvalDataset.is_active == True)
        .first()
    )
    if exists:
        raise HTTPException(status_code=400, detail="Dataset name already exists")

    ds = EvalDataset(
        knowledge_base_id=kb_id,
        name=name,
        description=data.description,
        created_by=data.created_by,
        is_active=True,
    )
    db.add(ds)
    db.commit()
    db.refresh(ds)
    out = ds.to_dict()
    out["cases_count"] = 0
    return out


@router.get("/knowledge-bases/{kb_id}/eval/datasets/export")
def export_all_eval_datasets(kb_id: int, db: Session = Depends(get_mysql_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, KnowledgeBase.is_active == True).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    datasets = (
        db.query(EvalDataset)
        .filter(EvalDataset.knowledge_base_id == kb_id, EvalDataset.is_active == True)
        .order_by(EvalDataset.updated_at.desc())
        .all()
    )

    out_items = []
    for ds in datasets:
        rows = (
            db.query(EvalCase, EvalCaseExpectation)
            .outerjoin(EvalCaseExpectation, EvalCaseExpectation.case_id == EvalCase.id)
            .filter(EvalCase.dataset_id == ds.id)
            .order_by(EvalCase.id.asc())
            .all()
        )
        out_items.append(
            {
                "dataset": ds.to_dict(),
                "cases": [_case_out(c, (e.expected_answer if e else None)) for (c, e) in rows],
            }
        )

    return {"knowledge_base": kb.to_dict(), "datasets": out_items}


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
def get_eval_dataset(kb_id: int, dataset_id: int, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")
    out = ds.to_dict()
    out["cases_count"] = db.query(EvalCase).filter(EvalCase.dataset_id == ds.id).count()
    return out


@router.put("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
def update_eval_dataset(kb_id: int, dataset_id: int, data: EvalDatasetUpdate, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if data.name is not None:
        name = data.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="name cannot be empty")

        exists = (
            db.query(EvalDataset)
            .filter(
                EvalDataset.knowledge_base_id == kb_id,
                EvalDataset.name == name,
                EvalDataset.is_active == True,
                EvalDataset.id != dataset_id,
            )
            .first()
        )
        if exists:
            raise HTTPException(status_code=400, detail="Dataset name already exists")
        ds.name = name
    if data.description is not None:
        ds.description = data.description
    if data.is_active is not None:
        ds.is_active = bool(data.is_active)

    db.commit()
    db.refresh(ds)
    out = ds.to_dict()
    out["cases_count"] = db.query(EvalCase).filter(EvalCase.dataset_id == ds.id).count()
    return out


@router.delete("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}")
def delete_eval_dataset(kb_id: int, dataset_id: int, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    ds.is_active = False
    db.commit()
    return {"message": "Dataset deleted"}


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases")
def list_eval_cases(
    kb_id: int,
    dataset_id: int,
    q: str | None = None,
    tag: str | None = None,
    offset: int = 0,
    limit: int = 200,
    db: Session = Depends(get_mysql_db),
):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    qv = (q or "").strip()
    tv = (tag or "").strip()
    off = int(offset or 0)
    lim = int(limit or 0)
    if off < 0:
        off = 0
    if lim <= 0:
        lim = 200
    if lim > 2000:
        lim = 2000

    base = db.query(EvalCase).filter(EvalCase.dataset_id == dataset_id)
    if qv:
        like = f"%{qv}%"
        base = base.filter(
            (EvalCase.query.like(like))
            | (EvalCase.notes.like(like))
            | (EvalCase.expected_sources.like(like))
            | (EvalCase.tags.like(like))
        )
    if tv:
        # tags are stored as JSON string; match exact quoted tag
        base = base.filter(EvalCase.tags.like(f'%"{tv}"%'))

    total = int(base.count())
    case_ids = [r[0] for r in base.with_entities(EvalCase.id).order_by(EvalCase.id.asc()).offset(off).limit(lim).all()]
    if not case_ids:
        return {"items": [], "total": total, "offset": off, "limit": lim}

    rows = (
        db.query(EvalCase, EvalCaseExpectation)
        .outerjoin(EvalCaseExpectation, EvalCaseExpectation.case_id == EvalCase.id)
        .filter(EvalCase.id.in_(case_ids))
        .order_by(EvalCase.id.asc())
        .all()
    )
    return {
        "items": [_case_out(c, (e.expected_answer if e else None)) for (c, e) in rows],
        "total": total,
        "offset": off,
        "limit": lim,
    }


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases")
def create_eval_case(kb_id: int, dataset_id: int, data: EvalCaseCreate, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    q = (data.query or "").strip()
    if not q:
        raise HTTPException(status_code=400, detail="query is required")

    row = EvalCase(
        dataset_id=dataset_id,
        query=q,
        expected_sources=json.dumps(list(data.expected_sources or []), ensure_ascii=False),
        notes=data.notes,
        tags=json.dumps(list(data.tags or []), ensure_ascii=False),
    )
    db.add(row)
    db.commit()
    db.refresh(row)

    expected_answer = (data.expected_answer or "").strip() if data.expected_answer is not None else None
    if expected_answer:
        db.add(EvalCaseExpectation(case_id=int(row.id), expected_answer=expected_answer))
        db.commit()

    return _case_out(row, expected_answer)


@router.put("/eval/cases/{case_id}")
def update_eval_case(case_id: int, data: EvalCaseUpdate, db: Session = Depends(get_mysql_db)):
    row = db.query(EvalCase).filter(EvalCase.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    if data.query is not None:
        q = data.query.strip()
        if not q:
            raise HTTPException(status_code=400, detail="query cannot be empty")
        row.query = q
    if data.expected_sources is not None:
        row.expected_sources = json.dumps(list(data.expected_sources or []), ensure_ascii=False)
    if data.notes is not None:
        row.notes = data.notes
    if data.tags is not None:
        row.tags = json.dumps(list(data.tags or []), ensure_ascii=False)

    expected_answer: str | None = None
    exp = db.query(EvalCaseExpectation).filter(EvalCaseExpectation.case_id == row.id).first()
    if data.expected_answer is not None:
        expected_answer = (data.expected_answer or "").strip()
        if expected_answer:
            if exp:
                exp.expected_answer = expected_answer
            else:
                db.add(EvalCaseExpectation(case_id=int(row.id), expected_answer=expected_answer))
        else:
            if exp:
                db.delete(exp)
    else:
        expected_answer = exp.expected_answer if exp else None

    db.commit()
    db.refresh(row)
    return _case_out(row, expected_answer)


@router.delete("/eval/cases/{case_id}")
def delete_eval_case(case_id: int, db: Session = Depends(get_mysql_db)):
    row = db.query(EvalCase).filter(EvalCase.id == case_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Case not found")

    exp = db.query(EvalCaseExpectation).filter(EvalCaseExpectation.case_id == row.id).first()
    if exp:
        db.delete(exp)

    db.delete(row)
    db.commit()
    return {"message": "Case deleted"}


class BulkDeleteCases(BaseModel):
    case_ids: List[int]


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/cases/bulk-delete")
def bulk_delete_eval_cases(kb_id: int, dataset_id: int, data: BulkDeleteCases, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    ids = [int(x) for x in (data.case_ids or []) if int(x) > 0]
    if not ids:
        return {"message": "No cases", "deleted": 0}

    rows = db.query(EvalCase).filter(EvalCase.dataset_id == dataset_id, EvalCase.id.in_(ids)).all()
    case_ids = [int(r.id) for r in rows]
    if not case_ids:
        return {"message": "No cases", "deleted": 0}

    db.query(EvalCaseExpectation).filter(EvalCaseExpectation.case_id.in_(case_ids)).delete(synchronize_session=False)
    db.query(EvalCase).filter(EvalCase.id.in_(case_ids)).delete(synchronize_session=False)
    db.commit()
    return {"message": "Deleted", "deleted": len(case_ids)}


@router.post("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/import")
def import_eval_dataset(kb_id: int, dataset_id: int, data: EvalDatasetImport, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    if data.replace:
        old_ids = [r[0] for r in db.query(EvalCase.id).filter(EvalCase.dataset_id == dataset_id).all()]
        if old_ids:
            db.query(EvalCaseExpectation).filter(EvalCaseExpectation.case_id.in_(old_ids)).delete(synchronize_session=False)
        db.query(EvalCase).filter(EvalCase.dataset_id == dataset_id).delete(synchronize_session=False)

    created = 0
    for c in data.cases or []:
        q = (c.query or "").strip()
        if not q:
            continue
        row = EvalCase(
            dataset_id=dataset_id,
            query=q,
            expected_sources=json.dumps(list(c.expected_sources or []), ensure_ascii=False),
            notes=c.notes,
            tags=json.dumps(list(c.tags or []), ensure_ascii=False),
        )
        db.add(row)
        db.flush()

        expected_answer = (c.expected_answer or "").strip() if c.expected_answer is not None else None
        if expected_answer:
            db.add(EvalCaseExpectation(case_id=int(row.id), expected_answer=expected_answer))
        created += 1

    db.commit()
    return {"message": "Imported", "created": created}


@router.get("/knowledge-bases/{kb_id}/eval/datasets/{dataset_id}/export")
def export_eval_dataset(kb_id: int, dataset_id: int, db: Session = Depends(get_mysql_db)):
    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    rows = (
        db.query(EvalCase, EvalCaseExpectation)
        .outerjoin(EvalCaseExpectation, EvalCaseExpectation.case_id == EvalCase.id)
        .filter(EvalCase.dataset_id == dataset_id)
        .order_by(EvalCase.id.asc())
        .all()
    )
    return {"dataset": ds.to_dict(), "cases": [_case_out(c, (e.expected_answer if e else None)) for (c, e) in rows]}


@router.post("/knowledge-bases/{kb_id}/eval/benchmarks/runs")
def create_benchmark_run(kb_id: int, data: BenchmarkRunCreate, db: Session = Depends(get_mysql_db)):
    kb = db.query(KnowledgeBase).filter(KnowledgeBase.id == kb_id, KnowledgeBase.is_active == True).first()
    if not kb:
        raise HTTPException(status_code=404, detail="Knowledge base not found")

    if data.mode not in ("vector", "graph", "qa"):
        raise HTTPException(status_code=400, detail="mode must be 'vector', 'graph' or 'qa'")
    if data.top_k <= 0 or data.top_k > 50:
        raise HTTPException(status_code=400, detail="top_k must be between 1 and 50")

    ds = (
        db.query(EvalDataset)
        .filter(EvalDataset.id == data.dataset_id, EvalDataset.knowledge_base_id == kb_id)
        .first()
    )
    if not ds or not ds.is_active:
        raise HTTPException(status_code=404, detail="Dataset not found")

    run = BenchmarkRun(
        knowledge_base_id=kb_id,
        dataset_id=int(data.dataset_id),
        mode=data.mode,
        top_k=int(data.top_k),
        status="queued",
        created_by=data.created_by,
    )
    db.add(run)
    db.commit()
    db.refresh(run)
    return run.to_dict()


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs")
def list_benchmark_runs(kb_id: int, db: Session = Depends(get_mysql_db)):
    runs = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.knowledge_base_id == kb_id)
        .order_by(BenchmarkRun.id.desc())
        .all()
    )
    return {"items": [r.to_dict() for r in runs]}


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}")
def get_benchmark_run(kb_id: int, run_id: int, db: Session = Depends(get_mysql_db)):
    run = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.id == run_id, BenchmarkRun.knowledge_base_id == kb_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run.to_dict()


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/results")
def list_benchmark_results(kb_id: int, run_id: int, db: Session = Depends(get_mysql_db)):
    run = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.id == run_id, BenchmarkRun.knowledge_base_id == kb_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    base_rows = (
        db.query(BenchmarkCaseResult)
        .filter(BenchmarkCaseResult.run_id == run_id)
        .order_by(BenchmarkCaseResult.id.asc())
        .all()
    )

    if run.mode != "qa":
        return {"items": [r.to_dict() for r in base_rows]}

    qa_rows = (
        db.query(BenchmarkQaResult)
        .filter(BenchmarkQaResult.run_id == run_id)
        .order_by(BenchmarkQaResult.id.asc())
        .all()
    )
    qa_map = {int(r.case_id): r for r in qa_rows}

    items = []
    for r in base_rows:
        d = r.to_dict()
        qa = qa_map.get(int(r.case_id))
        d["qa"] = qa.to_dict() if qa else None
        items.append(d)
    return {"items": items}


@router.get("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/export")
def export_benchmark_run(kb_id: int, run_id: int, db: Session = Depends(get_mysql_db)):
    run = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.id == run_id, BenchmarkRun.knowledge_base_id == kb_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    base_rows = (
        db.query(BenchmarkCaseResult)
        .filter(BenchmarkCaseResult.run_id == run_id)
        .order_by(BenchmarkCaseResult.id.asc())
        .all()
    )

    if run.mode != "qa":
        return {"run": run.to_dict(), "results": [r.to_dict() for r in base_rows]}

    qa_rows = (
        db.query(BenchmarkQaResult)
        .filter(BenchmarkQaResult.run_id == run_id)
        .order_by(BenchmarkQaResult.id.asc())
        .all()
    )
    qa_map = {int(r.case_id): r for r in qa_rows}
    results = []
    for r in base_rows:
        d = r.to_dict()
        qa = qa_map.get(int(r.case_id))
        d["qa"] = qa.to_dict() if qa else None
        results.append(d)
    return {"run": run.to_dict(), "results": results}


@router.post("/knowledge-bases/{kb_id}/eval/benchmarks/runs/{run_id}/execute")
async def execute_benchmark_run(
    kb_id: int,
    run_id: int,
    req: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_mysql_db),
):
    run = (
        db.query(BenchmarkRun)
        .filter(BenchmarkRun.id == run_id, BenchmarkRun.knowledge_base_id == kb_id)
        .first()
    )
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    request_id = _get_request_id_from_headers(req)
    if request_id:
        run.request_id = request_id
    run.status = "queued"
    run.error_message = None
    db.commit()
    db.refresh(run)

    from ..services.benchmark_runner import execute_benchmark_run as _fallback

    job_id = await _schedule_job(background_tasks, "execute_benchmark_run_job", _fallback, request_id, run.id)
    payload = run.to_dict()
    payload["job_id"] = job_id
    return payload
