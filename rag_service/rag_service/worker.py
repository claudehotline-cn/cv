"""ARQ worker for rag-service background jobs."""

from __future__ import annotations

import logging
from typing import Any, Dict

from arq.connections import RedisSettings

from .config import settings
from .services.ingestion import build_graph, process_document, rebuild_vectors
from .services.benchmark_runner import execute_benchmark_run
from .audit_emitter import AuditEmitter

logger = logging.getLogger(__name__)


_audit_redis = None
_audit_emitter: AuditEmitter | None = None


async def _get_audit_emitter() -> AuditEmitter:
    global _audit_redis, _audit_emitter
    if _audit_emitter is not None:
        return _audit_emitter

    import redis.asyncio as aioredis

    _audit_redis = aioredis.from_url(settings.redis_url, decode_responses=False)
    _audit_emitter = AuditEmitter(_audit_redis)
    return _audit_emitter


def _ctx_job_id(ctx: Dict[str, Any]) -> str | None:
    raw = ctx.get('job_id') or ctx.get('jobId') or ctx.get('id')
    if raw is None:
        return None
    return str(raw)


async def process_document_job(ctx: Dict[str, Any], document_id: int) -> None:
    job_id = _ctx_job_id(ctx)
    logger.info("[job] process_document document_id=%s job_id=%s", document_id, job_id)

    if job_id:
        emitter = await _get_audit_emitter()
        await emitter.emit(
            event_type="job_started",
            request_id=job_id,
            span_id=job_id,
            component="job",
            actor_type="service",
            actor_id="rag-worker",
            payload={"action": "process_document", "document_id": document_id},
        )

    try:
        await process_document(document_id)
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_completed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={"action": "process_document", "document_id": document_id},
            )
    except Exception as e:
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_failed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={
                    "action": "process_document",
                    "document_id": document_id,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                },
            )
        raise


async def rebuild_vectors_job(ctx: Dict[str, Any], kb_id: int) -> None:
    job_id = _ctx_job_id(ctx)
    logger.info("[job] rebuild_vectors kb_id=%s job_id=%s", kb_id, job_id)

    if job_id:
        emitter = await _get_audit_emitter()
        await emitter.emit(
            event_type="job_started",
            request_id=job_id,
            span_id=job_id,
            component="job",
            actor_type="service",
            actor_id="rag-worker",
            payload={"action": "rebuild_vectors", "kb_id": kb_id},
        )

    try:
        await rebuild_vectors(kb_id)
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_completed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={"action": "rebuild_vectors", "kb_id": kb_id},
            )
    except Exception as e:
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_failed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={
                    "action": "rebuild_vectors",
                    "kb_id": kb_id,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                },
            )
        raise


async def build_graph_job(ctx: Dict[str, Any], kb_id: int) -> None:
    job_id = _ctx_job_id(ctx)
    logger.info("[job] build_graph kb_id=%s job_id=%s", kb_id, job_id)

    if job_id:
        emitter = await _get_audit_emitter()
        await emitter.emit(
            event_type="job_started",
            request_id=job_id,
            span_id=job_id,
            component="job",
            actor_type="service",
            actor_id="rag-worker",
            payload={"action": "build_graph", "kb_id": kb_id},
        )

    try:
        await build_graph(kb_id)
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_completed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={"action": "build_graph", "kb_id": kb_id},
            )
    except Exception as e:
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_failed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={
                    "action": "build_graph",
                    "kb_id": kb_id,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                },
            )
        raise


async def execute_benchmark_run_job(ctx: Dict[str, Any], run_id: int) -> None:
    job_id = _ctx_job_id(ctx)
    logger.info("[job] execute_benchmark_run run_id=%s job_id=%s", run_id, job_id)

    if job_id:
        emitter = await _get_audit_emitter()
        await emitter.emit(
            event_type="job_started",
            request_id=job_id,
            span_id=job_id,
            component="job",
            actor_type="service",
            actor_id="rag-worker",
            payload={"action": "benchmark_execute", "run_id": run_id},
        )

    try:
        await execute_benchmark_run(run_id)
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_completed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={"action": "benchmark_execute", "run_id": run_id},
            )
    except Exception as e:
        if job_id:
            emitter = await _get_audit_emitter()
            await emitter.emit(
                event_type="job_failed",
                request_id=job_id,
                span_id=job_id,
                component="job",
                actor_type="service",
                actor_id="rag-worker",
                payload={
                    "action": "benchmark_execute",
                    "run_id": run_id,
                    "error_message": str(e),
                    "error_class": type(e).__name__,
                },
            )
        raise


class WorkerSettings:
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = settings.queue_name
    functions = [
        process_document_job,
        rebuild_vectors_job,
        build_graph_job,
        execute_benchmark_run_job,
    ]
    job_timeout = 60 * 60  # 1 hour
    max_jobs = 1
