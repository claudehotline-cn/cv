"""Benchmark runner for RAG retrieval evaluation."""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from ..config import settings
from ..database import MySQLSessionLocal
from ..models import (
    BenchmarkCaseResult,
    BenchmarkQaResult,
    BenchmarkRun,
    Document,
    EvalCase,
    EvalCaseExpectation,
    EvalDataset,
)
from .retriever import rag_retriever
from .graph_retriever import graph_retriever

logger = logging.getLogger(__name__)


_stream_redis = None


def _benchmark_stream_key(run_id: int) -> str:
    return f"rag:benchmark_run:{int(run_id)}:stream"


async def _get_stream_redis():
    global _stream_redis
    if _stream_redis is not None:
        return _stream_redis

    import redis.asyncio as aioredis

    _stream_redis = aioredis.from_url(settings.redis_url, decode_responses=True)
    return _stream_redis


async def _emit_benchmark_event(run_id: int, event: dict[str, Any]) -> None:
    try:
        r = await _get_stream_redis()
        payload: dict[str, Any] = {}
        for k, v in (event or {}).items():
            if v is None:
                continue
            if isinstance(v, (str, int, float)):
                payload[str(k)] = v
            else:
                payload[str(k)] = json.dumps(v, ensure_ascii=False)
        if not payload:
            return
        await r.xadd(_benchmark_stream_key(run_id), payload, maxlen=2000, approximate=True)
    except Exception:
        # Progress streaming is best-effort.
        logger.exception("[benchmark] failed to publish progress event run_id=%s", run_id)


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


def _extract_json_obj(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    s = text.strip()
    # Try whole string
    try:
        val = json.loads(s)
        return val if isinstance(val, dict) else None
    except Exception:
        pass

    # Try fenced ```json
    m = re.search(r"```json\s*(\{.*?\})\s*```", s, re.DOTALL)
    if m:
        try:
            val = json.loads(m.group(1))
            return val if isinstance(val, dict) else None
        except Exception:
            return None

    # Try first {...}
    m = re.search(r"(\{.*\})", s, re.DOTALL)
    if not m:
        return None
    try:
        val = json.loads(m.group(1))
        return val if isinstance(val, dict) else None
    except Exception:
        return None


def _normalize_text(s: str) -> str:
    s = (s or "").strip().lower()
    return re.sub(r"\s+", " ", s)


def _fallback_answer_score(expected_answer: str, answer: str) -> float:
    """Heuristic fallback scoring when LLM judge output is not parseable."""
    exp = _normalize_text(expected_answer)
    ans = _normalize_text(answer)
    if not exp:
        return 0.0
    if exp == ans:
        return 1.0
    if exp in ans:
        return 0.8
    return 0.0


async def _judge_answer(question: str, expected_answer: str, answer: str, *, sources_preview: str) -> tuple[float | None, dict[str, Any] | None]:
    from .llm_service import llm_service

    system = (
        "You are a strict evaluator for answer quality. "
        "Given a question, an expected answer, the model answer, and optional context preview, "
        "score the model answer from 0.0 to 1.0 based on correctness and completeness relative to the expected answer. "
        "Return ONLY valid JSON with keys: score (number), verdict (string), reasons (array of strings). "
        "Do not output any other text. Do not include thinking." 
    )
    user = (
        f"Question:\n{question}\n\n"
        f"Expected Answer:\n{expected_answer}\n\n"
        f"Model Answer:\n{answer}\n\n"
        f"Sources Preview (may be partial):\n{sources_preview}\n"
    )

    raw = await llm_service.generate_messages(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.0,
        max_tokens=256,
    )
    obj = _extract_json_obj(raw) or None
    if not obj:
        return None, None

    score = obj.get("score")
    try:
        score_f = float(score)
    except Exception:
        score_f = None
    if score_f is not None:
        score_f = max(0.0, min(1.0, score_f))
    return score_f, obj


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
        db.query(BenchmarkQaResult).filter(BenchmarkQaResult.run_id == run.id).delete()
        run.status = "running"
        run.error_message = None
        run.started_at = datetime.utcnow()
        run.ended_at = None
        run.metrics = None
        db.commit()
        db.refresh(run)

        exp_rows = (
            db.query(EvalCaseExpectation)
            .filter(EvalCaseExpectation.case_id.in_([int(c.id) for c in cases]))
            .all()
        )
        exp_map = {int(r.case_id): (r.expected_answer or "") for r in exp_rows}

    logger.info(
        "[benchmark] start run_id=%s kb_id=%s dataset_id=%s mode=%s top_k=%s",
        run_id,
        run.knowledge_base_id,
        run.dataset_id,
        run.mode,
        run.top_k,
    )

    total_cases = len(cases)
    await _emit_benchmark_event(
        int(run_id),
        {
            "type": "benchmark_status",
            "run_id": int(run_id),
            "knowledge_base_id": int(run.knowledge_base_id),
            "dataset_id": int(run.dataset_id),
            "mode": str(run.mode),
            "top_k": int(run.top_k or 5),
            "status": "running",
            "progress": 0,
            "total_cases": total_cases,
        },
    )

    try:
        sums = {"mrr": 0.0, "ndcg": 0.0, "hit": 0.0}
        qa_sums = {"score": 0.0, "scored": 0, "pass": 0}
        total = 0

        if not cases:
            agg = {
                "total_cases": 0,
                "hit_rate": 0.0,
                "mrr": 0.0,
                "ndcg": 0.0,
            }
            with MySQLSessionLocal() as db:
                run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
                if run:
                    run.status = "succeeded"
                    run.metrics = json.dumps(agg, ensure_ascii=False)
                    run.ended_at = datetime.utcnow()
                    db.commit()

            await _emit_benchmark_event(
                int(run_id),
                {
                    "type": "benchmark_completed",
                    "run_id": int(run_id),
                    "status": "succeeded",
                    "progress": 100,
                    "metrics": agg,
                },
            )
            return

        for idx, c in enumerate(cases, start=1):
            expected_sources = _load_list(c.expected_sources)

            expected_answer = exp_map.get(int(c.id))
            expected_answer = expected_answer.strip() if expected_answer else ""

            retrieved: list[dict[str, Any]] = []
            retrieved_sources: list[str] = []

            if run.mode == "qa":
                resp = await rag_retriever.answer(
                    query=c.query,
                    knowledge_base_id=int(run.knowledge_base_id),
                    top_k=int(run.top_k or 5),
                    use_graph=False,
                    enable_query_expansion=False,
                    expand_to_parent=False,
                    compress_context=False,
                    enable_rerank=False,
                )

                # Build sources list and filenames for retrieval metrics.
                src_items = list(resp.sources or [])
                doc_ids = [
                    int(s.get("document_id"))
                    for s in src_items
                    if isinstance(s, dict) and s.get("type") == "vector" and s.get("document_id")
                ]
                name_map: dict[int, str] = {}
                if doc_ids:
                    with MySQLSessionLocal() as db:
                        docs = db.query(Document.id, Document.filename).filter(Document.id.in_(doc_ids)).all()
                        name_map = {int(i): str(n) for (i, n) in docs}

                for i, s in enumerate(src_items, start=1):
                    if not isinstance(s, dict):
                        continue
                    doc_id = int(s.get("document_id") or 0)
                    src_name = name_map.get(doc_id, "") if doc_id else ""
                    retrieved_sources.append(src_name)
                    retrieved.append(
                        {
                            "rank": i,
                            "type": str(s.get("type") or ""),
                            "document_id": doc_id,
                            "chunk_index": int(s.get("chunk_index") or 0),
                            "score": float(s.get("score") or 0.0),
                            "source": src_name,
                            "content": s.get("content_preview"),
                        }
                    )

                metrics = _compute_metrics(expected_sources, retrieved_sources)

                # Persist retrieval metrics and raw answer in JSON.
                with MySQLSessionLocal() as db:
                    db.add(
                        BenchmarkCaseResult(
                            run_id=int(run_id),
                            case_id=int(c.id),
                            hit_rank=metrics["hit_rank"],
                            mrr=float(metrics["mrr"]),
                            ndcg=float(metrics["ndcg"]),
                            retrieved=json.dumps(
                                {
                                    "expected_sources": expected_sources,
                                    "retrieved": retrieved,
                                    "expected_answer": expected_answer or None,
                                    "answer": resp.answer,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                    db.commit()

                # Answer-level judging (optional if expected_answer is present).
                score = None
                judge_obj = None
                if expected_answer:
                    preview = "\n".join(
                        [
                            f"[{i+1}] {str(x.get('content_preview') or '')[:240]}" for i, x in enumerate(src_items)
                            if isinstance(x, dict)
                        ]
                    )
                    score, judge_obj = await _judge_answer(
                        c.query,
                        expected_answer,
                        resp.answer,
                        sources_preview=preview,
                    )

                    if score is None:
                        score = _fallback_answer_score(expected_answer, resp.answer)
                        judge_obj = {
                            "score": score,
                            "verdict": "heuristic",
                            "reasons": ["LLM judge output was not parseable; used heuristic scoring"],
                        }

                with MySQLSessionLocal() as db:
                    db.add(
                        BenchmarkQaResult(
                            run_id=int(run_id),
                            case_id=int(c.id),
                            expected_answer=expected_answer or None,
                            answer=resp.answer,
                            score=score,
                            judge=json.dumps(judge_obj, ensure_ascii=False) if judge_obj is not None else None,
                            sources=json.dumps(src_items, ensure_ascii=False) if src_items is not None else None,
                        )
                    )
                    db.commit()

                if score is not None:
                    qa_sums["score"] += float(score)
                    qa_sums["scored"] += 1
                    if float(score) >= 0.8:
                        qa_sums["pass"] += 1

                sums["mrr"] += float(metrics["mrr"])
                sums["ndcg"] += float(metrics["ndcg"])
                sums["hit"] += float(metrics["hit"])
                total += 1

                await _emit_benchmark_event(
                    int(run_id),
                    {
                        "type": "benchmark_progress",
                        "run_id": int(run_id),
                        "status": "running",
                        "progress": int((idx / total_cases) * 100),
                        "current": idx,
                        "total": total_cases,
                        "case_id": int(c.id),
                        "hit_rank": metrics.get("hit_rank"),
                        "qa_score": score,
                    },
                )
                continue

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

            await _emit_benchmark_event(
                int(run_id),
                {
                    "type": "benchmark_progress",
                    "run_id": int(run_id),
                    "status": "running",
                    "progress": int((idx / total_cases) * 100),
                    "current": idx,
                    "total": total_cases,
                    "case_id": int(c.id),
                    "hit_rank": metrics.get("hit_rank"),
                },
            )

        agg = {
            "total_cases": total,
            "hit_rate": (sums["hit"] / total) if total else 0.0,
            "mrr": (sums["mrr"] / total) if total else 0.0,
            "ndcg": (sums["ndcg"] / total) if total else 0.0,
        }

        if run.mode == "qa":
            scored = int(qa_sums["scored"])
            agg["qa"] = {
                "scored_cases": scored,
                "avg_score": (qa_sums["score"] / scored) if scored else None,
                "pass_rate": (qa_sums["pass"] / scored) if scored else None,
            }

        with MySQLSessionLocal() as db:
            run = db.query(BenchmarkRun).filter(BenchmarkRun.id == run_id).first()
            if not run:
                return
            run.status = "succeeded"
            run.metrics = json.dumps(agg, ensure_ascii=False)
            run.ended_at = datetime.utcnow()
            db.commit()

        await _emit_benchmark_event(
            int(run_id),
            {
                "type": "benchmark_completed",
                "run_id": int(run_id),
                "status": "succeeded",
                "progress": 100,
                "metrics": agg,
            },
        )

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

        await _emit_benchmark_event(
            int(run_id),
            {
                "type": "benchmark_failed",
                "run_id": int(run_id),
                "status": "failed",
                "progress": 100,
                "error_message": str(e),
            },
        )
        raise
