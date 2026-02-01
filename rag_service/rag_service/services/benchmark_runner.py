"""Benchmark runner for RAG retrieval evaluation."""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..database import MySQLSessionLocal
from ..models import BenchmarkCaseResult, BenchmarkRun, EvalCase, EvalDataset
from .retriever import rag_retriever
from .graph_retriever import graph_retriever

logger = logging.getLogger(__name__)


def _normalize_source(s: str) -> str:
    return (s or "").strip().lower()


def _load_list(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        if isinstance(val, list):
            return [str(x) for x in val if str(x).strip()]
        return []
    except Exception:
        return []


def _compute_metrics(expected_sources: list[str], retrieved_sources: list[str]) -> dict[str, Any]:
    expected = {_normalize_source(s) for s in expected_sources if _normalize_source(s)}
    rels: list[int] = []
    hit_rank: Optional[int] = None

    for i, s in enumerate(retrieved_sources, start=1):
        is_rel = 1 if (_normalize_source(s) in expected) else 0
        rels.append(is_rel)
        if hit_rank is None and is_rel:
            hit_rank = i

    mrr = 1.0 / hit_rank if hit_rank else 0.0

    # binary nDCG
    dcg = 0.0
    for i, rel in enumerate(rels, start=1):
        if not rel:
            continue
        dcg += 1.0 / math.log2(i + 1)

    # ideal DCG: all relevant at top. If expected is empty, nDCG is 0.
    ideal_rels = [1] * min(len(expected), len(rels))
    idcg = 0.0
    for i, rel in enumerate(ideal_rels, start=1):
        if not rel:
            continue
        idcg += 1.0 / math.log2(i + 1)

    ndcg = (dcg / idcg) if idcg > 0 else 0.0

    return {
        "hit_rank": hit_rank,
        "mrr": mrr,
        "ndcg": ndcg,
        "hit": 1 if hit_rank else 0,
    }


async def execute_benchmark_run(run_id: int) -> None:
    """Execute a benchmark run and persist results."""
    with MySQLSessionLocal() as db:
        run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
        if not run:
            raise ValueError(f"Benchmark run not found: {run_id}")

        dataset = db.query(EvalDataset).filter(EvalDataset.id == run.dataset_id).first()
        if not dataset or not dataset.is_active:
            raise ValueError(f"Dataset not found or inactive: {run.dataset_id}")
        if int(dataset.knowledge_base_id) != int(run.knowledge_base_id):
            raise ValueError("Dataset does not belong to the benchmark run knowledge base")

        cases = (
            db.query(EvalCase)
            .filter(EvalCase.dataset_id == dataset.id)
            .order_by(EvalCase.id.asc())
            .all()
        )

        # reset state
        db.query(BenchmarkCaseResult).filter(BenchmarkCaseResult.run_id == run.id).delete()
        run.status = "running"
        run.error_message = None
        run.started_at = datetime.utcnow()
        run.ended_at = None
        run.metrics = None
        db.commit()
        db.refresh(run)

    logger.info(
        "[benchmark] start run_id=%s kb_id=%s dataset_id=%s mode=%s top_k=%s",
        run_id,
        run.knowledge_base_id,
        run.dataset_id,
        run.mode,
        run.top_k,
    )

    try:
        sums = {"mrr": 0.0, "ndcg": 0.0, "hit": 0.0}
        total = 0

        for c in cases:
            expected_sources = _load_list(c.expected_sources)

            retrieved: list[dict[str, Any]] = []
            retrieved_sources: list[str] = []

            if run.mode == "graph":
                items = await graph_retriever.retrieve(
                    query=c.query,
                    knowledge_base_id=int(run.knowledge_base_id),
                    depth=2,
                )
                # graph retriever doesn't have top_k; truncate.
                items = items[: int(run.top_k or 5)]
                for i, it in enumerate(items, start=1):
                    meta = (it.get("metadata") or {}) if isinstance(it, dict) else {}
                    src = str(meta.get("source") or "")
                    retrieved_sources.append(src)
                    retrieved.append(
                        {
                            "rank": i,
                            "type": "graph",
                            "score": float(it.get("score") or 0.0) if isinstance(it, dict) else 0.0,
                            "source": src,
                            "content": it.get("content") if isinstance(it, dict) else None,
                            "metadata": meta,
                        }
                    )
            else:
                items = await rag_retriever.retrieve(
                    query=c.query,
                    knowledge_base_id=int(run.knowledge_base_id),
                    top_k=int(run.top_k or 5),
                    enable_query_expansion=False,
                    expand_to_parent=False,
                    compress_context=False,
                )
                for i, it in enumerate(items, start=1):
                    src = str((it.metadata or {}).get("source") or (it.metadata or {}).get("filename") or "")
                    retrieved_sources.append(src)
                    retrieved.append(
                        {
                            "rank": i,
                            "type": "vector",
                            "score": float(it.score or 0.0),
                            "document_id": int(it.document_id),
                            "chunk_index": int(it.chunk_index),
                            "source": src,
                            "content": it.content,
                            "metadata": it.metadata,
                        }
                    )

            metrics = _compute_metrics(expected_sources, retrieved_sources)

            with MySQLSessionLocal() as db:
                row = BenchmarkCaseResult(
                    run_id=int(run_id),
                    case_id=int(c.id),
                    hit_rank=metrics["hit_rank"],
                    mrr=float(metrics["mrr"]),
                    ndcg=float(metrics["ndcg"]),
                    retrieved=json.dumps(
                        {
                            "expected_sources": expected_sources,
                            "retrieved": retrieved,
                        },
                        ensure_ascii=False,
                    ),
                )
                db.add(row)
                db.commit()

            sums["mrr"] += float(metrics["mrr"])
            sums["ndcg"] += float(metrics["ndcg"])
            sums["hit"] += float(metrics["hit"])
            total += 1

        agg = {
            "total_cases": total,
            "hit_rate": (sums["hit"] / total) if total else 0.0,
            "mrr": (sums["mrr"] / total) if total else 0.0,
            "ndcg": (sums["ndcg"] / total) if total else 0.0,
        }

        with MySQLSessionLocal() as db:
            run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
            if not run:
                return
            run.status = "succeeded"
            run.metrics = json.dumps(agg, ensure_ascii=False)
            run.ended_at = datetime.utcnow()
            db.commit()

        logger.info("[benchmark] done run_id=%s total=%s", run_id, total)
    except Exception as e:
        logger.exception("[benchmark] failed run_id=%s", run_id)
        with MySQLSessionLocal() as db:
            run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
            if run:
                run.status = "failed"
                run.error_message = str(e)
                run.ended_at = datetime.utcnow()
                db.commit()
        raise
