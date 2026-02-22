"""ARQ Worker 配置和任务函数"""

import asyncio
import logging
from datetime import datetime
import os
from typing import Any, Dict
from uuid import UUID, uuid4

from arq import ArqRedis
from arq.connections import RedisSettings

from agent_core.settings import get_settings
from app.core.governance import GovernanceKeys, release_execute_concurrency
from app.utils.interrupts import extract_interrupt_data
from app.utils.session_memory import format_recent_messages_for_prompt

_LOGGER = logging.getLogger("agent_platform.worker")
settings = get_settings()

print("DEBUG: [Worker] Module app.worker imported", flush=True)
try:
    with open("/tmp/module_loaded.txt", "w") as f:
        f.write(f"Imported at {datetime.utcnow()}")
except:
    pass


async def agent_execute_task(
    ctx: Dict[str, Any],
    task_id: str,
    session_id: str,
    agent_key: str,

    input_message: str,
    config: Dict[str, Any] = None,
    user_id: str = "default",
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    thread_id: str = None
) -> Dict[str, Any]:
    """执行 Agent 任务
    
    Args:
        ctx: ARQ 上下文（包含 redis 连接）
        task_id: 任务 ID
        session_id: 会话 ID
        agent_key: Agent 标识（如 data_agent）
        input_message: 用户输入
        config: 额外配置
    """
    from app.db import AsyncSessionLocal
    from app.services.task_service import TaskService
    from app.core.agent_registry import registry
    
    _LOGGER.info(f"[Worker] Starting task {task_id} for agent {agent_key}")
    print(f"[WORKER DEBUG] Code reload check: timestamp {datetime.utcnow()}", flush=True)
    
    # Init EventBus
    from agent_core.events import RedisEventBus
    event_bus = RedisEventBus(settings.redis_url)
    from agent_core.audit import AuditCallbackHandler
    from agent_core.events import AuditEmitter
    audit_redis = None
    audit_emitter = None
    
    async with AsyncSessionLocal() as db:
        task_service = TaskService(db)

        async def emit_task_event(event_type: str, payload: Dict[str, Any]) -> None:
            """Emit task events to both per-task and per-session streams."""
            event: Dict[str, Any] = {
                "type": event_type,
                "task_id": task_id,
                "session_id": session_id,
                "agent_key": agent_key,
                "title": (input_message or "")[:80],
                **payload,
            }
            # Per-task stream (legacy / debug)
            await event_bus.publish(f"task:{task_id}:stream", event)
            # Per-session stream (primary)
            await event_bus.publish(f"session:{session_id}:tasks", event)
        
        # 更新状态为 running
        await task_service.update_status(
            UUID(task_id), 
            status="running", 
            started_at=datetime.utcnow()
        )
        await task_service.update_progress(UUID(task_id), 10, "正在初始化 Agent...")
        await emit_task_event("task_progress", {"status": "running", "progress": 10, "message": "正在初始化 Agent..."})
        
        # Business Request ID (FK for audit) = task_id
        request_id = str(UUID(task_id)) if task_id else str(uuid4())
        effective_thread_id = thread_id or session_id

        # Init AuditEmitter early so job lifecycle is always captured
        import redis as redis_lib
        audit_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=False)
        audit_emitter = AuditEmitter(redis=audit_redis)

        async def emit_job_event(event_type: str, payload: Dict[str, Any]) -> None:
            try:
                await audit_emitter.emit(
                    event_type=event_type,
                    request_id=request_id,
                    span_id=task_id,
                    session_id=session_id,
                    thread_id=effective_thread_id,
                    component="job",
                    actor_type="service",
                    actor_id=os.getenv("HOSTNAME", "agent-worker"),
                    payload=payload,
                )
            except Exception:
                pass

        await emit_job_event(
            "job_started",
            {
                "agent_key": agent_key,
                "title": (input_message or "")[:120],
            },
        )

        try:
            # 加载 Agent
            agent = registry.get_plugin(agent_key)
            if not agent:
                raise ValueError(f"Agent not found: {agent_key}")
            graph = agent.get_graph()
            
            await task_service.update_progress(UUID(task_id), 20, "Agent 已加载，开始执行...")
            await emit_task_event("task_progress", {"status": "running", "progress": 20, "message": "Agent 已加载，开始执行..."})
            await emit_job_event("job_progress", {"progress": 20, "message": "Agent 已加载，开始执行..."})
            
            # 检查取消
            if await task_service.is_cancel_requested(UUID(task_id)):
                await task_service.update_status(
                    UUID(task_id), 
                    status="cancelled",
                    completed_at=datetime.utcnow()
                )
                await emit_task_event("task_cancelled", {"status": "cancelled", "progress": 100, "message": "已取消"})
                return {"cancelled": True}
            
            # 执行 Agent（内部流式，仅用于驱动进度，不向前端输出 chunk）
            progress = 20
            
            # Inject task_id and user_id into config
            config = config or {}
            config["audit_emitter"] = audit_emitter

            audit_callback = AuditCallbackHandler(emitter=audit_emitter)
            existing_callbacks = config.get("callbacks")
            if existing_callbacks is None:
                config["callbacks"] = [audit_callback]
            elif isinstance(existing_callbacks, list):
                config["callbacks"] = [*existing_callbacks, audit_callback]
            else:
                add_handler = getattr(existing_callbacks, "add_handler", None)
                if callable(add_handler):
                    add_handler(audit_callback)
                else:
                    config["callbacks"] = [existing_callbacks, audit_callback]

            config.setdefault("configurable", {})
            config["configurable"]["task_id"] = task_id
            config["configurable"]["user_id"] = user_id
            config["configurable"]["session_id"] = session_id
            # data_agent 需要 analysis_id 来隔离工作区（data_analysis_{analysis_id}）。
            # 异步任务允许同一 session 多任务并行，因此这里用 task_id（每个任务唯一）
            # 而不是 session_id，避免写入同一目录互相覆盖产物。
            if agent_key == "data_agent":
                config["configurable"].setdefault("analysis_id", task_id)
            config["configurable"]["thread_id"] = effective_thread_id
            
            # Inject request_id into metadata so AuditCallbackHandler can link Spans to this Request
            config.setdefault("metadata", {})
            config["metadata"]["session_id"] = session_id
            config["metadata"]["thread_id"] = effective_thread_id
            config["metadata"]["request_id"] = request_id
            config["metadata"]["sub_agent"] = agent_key 
            # Also inject user info if needed
            config["metadata"]["user_id"] = user_id
            # Tags are critical for audit instrumentation to correctly identify the
            # root agent run and emit run_finished/run_interrupted events.
            config.setdefault("tags", [])
            if agent_key not in config["tags"]:
                config["tags"].append(agent_key)
            if "agent_platform" not in config["tags"]:
                config["tags"].append("agent_platform")
            if "async_task" not in config["tags"]:
                config["tags"].append("async_task")

            # NOTE: We DO NOT set config["run_id"]. We let LangChain generate a native UUID for the Root Span.
            # This decouples the "Request" (DB Run) from the "Trace" (Execution Graph).

            shared_context = ""
            try:
                from agent_core.store import get_async_store

                store = await get_async_store()
                item = await store.aget(("agent_platform", "sessions", str(session_id)), "recent_messages")
                if item and isinstance(getattr(item, "value", None), dict):
                    recent = item.value.get("messages")
                    if isinstance(recent, list) and recent:
                        shared_context = format_recent_messages_for_prompt(recent)
            except Exception:
                shared_context = ""

            messages = []
            if shared_context:
                messages.append(
                    {
                        "role": "system",
                        "content": "以下是该会话近期对话内容（供参考）：\n" + shared_context,
                    }
                )
            messages.append({"role": "user", "content": input_message})

            async for _chunk in graph.astream(
                {"messages": messages},
                config=config
            ):
                # 更新进度（简单递增，最多到 90）
                new_progress = min(90, progress + 5)
                if new_progress != progress:
                    progress = new_progress
                    await task_service.update_progress(UUID(task_id), progress, "执行中...")
                    await emit_task_event(
                        "task_progress",
                        {"status": "running", "progress": progress, "message": "执行中..."},
                    )
                    await emit_job_event("job_progress", {"progress": progress, "message": "执行中..."})
                
                # 检查取消
                if await task_service.is_cancel_requested(UUID(task_id)):
                    await task_service.update_status(
                        UUID(task_id), 
                        status="cancelled",
                        completed_at=datetime.utcnow()
                    )
                    await emit_task_event("task_cancelled", {"status": "cancelled", "progress": 100, "message": "已取消"})
                    await emit_job_event("job_cancelled", {"reason": "user_requested"})
                    return {"cancelled": True}

            # HITL: check if execution ended due to an interrupt (waiting for approval)
            interrupt_data = None
            try:
                state = await graph.aget_state(config)
                interrupt_data = extract_interrupt_data(state)
            except Exception:
                interrupt_data = None

            if interrupt_data:
                paused_result = {
                    "success": False,
                    "interrupted": True,
                    "interrupt_data": interrupt_data,
                    "audit_run_id": request_id,
                    "audit_url": f"/audit?q={request_id}",
                }
                await task_service.update_status(
                    UUID(task_id),
                    status="waiting_approval",
                    result=paused_result,
                )
                await task_service.update_progress(UUID(task_id), 90, "等待人工确认")
                await emit_task_event(
                    "task_waiting_approval",
                    {
                        "status": "waiting_approval",
                        "progress": 90,
                        "message": "等待人工确认",
                        "interrupt_data": interrupt_data,
                        "result": paused_result,
                    },
                )
                await emit_job_event(
                    "job_waiting_approval",
                    {
                        "interrupt_data": interrupt_data,
                    },
                )
                _LOGGER.info(f"[Worker] Task {task_id} waiting for approval (interrupt)")
                return paused_result
            
            # 完成
            final_result = {
                "success": True,
                "audit_run_id": request_id,
                "audit_url": f"/audit?q={request_id}",
            }
            await task_service.update_status(
                UUID(task_id),
                status="completed",
                completed_at=datetime.utcnow(),
                result=final_result
            )
            await task_service.update_progress(UUID(task_id), 100, "完成")
            await emit_task_event(
                "task_completed",
                {"status": "completed", "progress": 100, "message": "完成", "result": final_result},
            )
            await emit_job_event(
                "job_completed",
                {
                    "result": final_result,
                },
            )
            
            _LOGGER.info(f"[Worker] Task {task_id} completed successfully")
            return final_result
            
        except Exception as e:
            _LOGGER.error(f"[Worker] Task {task_id} failed: {e}")
            await task_service.update_status(
                UUID(task_id),
                status="failed",
                completed_at=datetime.utcnow(),
                error=str(e)
            )
            await emit_task_event(
                "task_failed",
                {"status": "failed", "progress": 100, "message": "失败", "error": str(e)},
            )
            await emit_job_event(
                "job_failed",
                {
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:2000],
                },
            )
            return {"error": str(e)}
        finally:
            try:
                await release_execute_concurrency(GovernanceKeys(tenant_id=tenant_id, user_id=user_id))
            except Exception:
                pass
            try:
                await event_bus.close()
            except Exception:
                pass
            if audit_redis is not None:
                try:
                    audit_redis.close()
                except Exception:
                    pass


async def agent_resume_task(
    ctx: Dict[str, Any],
    task_id: str,
    session_id: str,
    agent_key: str,
    decision: str,
    feedback: str = "",
    config: Dict[str, Any] = None,
    user_id: str = "default",
    tenant_id: str = "00000000-0000-0000-0000-000000000001",
    thread_id: str = None,
) -> Dict[str, Any]:
    """Resume an interrupted async task (HITL)."""
    from datetime import datetime
    from uuid import UUID

    from app.db import AsyncSessionLocal
    from app.models.db_models import TaskModel
    from app.services.task_service import TaskService
    from app.core.agent_registry import registry

    _LOGGER.info(f"[Worker] Resuming task {task_id} for agent {agent_key}")

    from agent_core.events import RedisEventBus, AuditEmitter
    from agent_core.audit import AuditCallbackHandler

    event_bus = RedisEventBus(settings.redis_url)
    audit_redis = None
    audit_emitter = None

    async with AsyncSessionLocal() as db:
        task_service = TaskService(db)

        task: TaskModel | None = await task_service.get_task(UUID(task_id))
        input_message = ""
        if task and isinstance(task.result, dict):
            input_message = str(task.result.get("input_message") or "")

        async def emit_task_event(event_type: str, payload: Dict[str, Any]) -> None:
            event: Dict[str, Any] = {
                "type": event_type,
                "task_id": task_id,
                "session_id": session_id,
                "agent_key": agent_key,
                "title": (input_message or "")[:80],
                **payload,
            }
            await event_bus.publish(f"task:{task_id}:stream", event)
            await event_bus.publish(f"session:{session_id}:tasks", event)

        request_id = str(UUID(task_id))
        effective_thread_id = thread_id or session_id

        import redis as redis_lib
        audit_redis = redis_lib.Redis.from_url(settings.redis_url, decode_responses=False)
        audit_emitter = AuditEmitter(redis=audit_redis)

        async def emit_job_event(event_type: str, payload: Dict[str, Any]) -> None:
            try:
                await audit_emitter.emit(
                    event_type=event_type,
                    request_id=request_id,
                    span_id=task_id,
                    session_id=session_id,
                    thread_id=effective_thread_id,
                    component="job",
                    actor_type="service",
                    actor_id=os.getenv("HOSTNAME", "agent-worker"),
                    payload=payload,
                )
            except Exception:
                pass

        await emit_job_event("job_resumed", {"decision": decision})

        try:
            await task_service.update_status(UUID(task_id), status="running")
            await task_service.update_progress(UUID(task_id), 90, "继续执行...")
            await emit_task_event(
                "task_progress",
                {"status": "running", "progress": 90, "message": "继续执行..."},
            )

            agent = registry.get_plugin(agent_key)
            if not agent:
                raise ValueError(f"Agent not found: {agent_key}")
            graph = agent.get_graph()

            config = config or {}
            config["audit_emitter"] = audit_emitter

            audit_callback = AuditCallbackHandler(emitter=audit_emitter)
            existing_callbacks = config.get("callbacks")
            if existing_callbacks is None:
                config["callbacks"] = [audit_callback]
            elif isinstance(existing_callbacks, list):
                config["callbacks"] = [*existing_callbacks, audit_callback]
            else:
                add_handler = getattr(existing_callbacks, "add_handler", None)
                if callable(add_handler):
                    add_handler(audit_callback)
                else:
                    config["callbacks"] = [existing_callbacks, audit_callback]

            config.setdefault("configurable", {})
            config["configurable"]["task_id"] = task_id
            config["configurable"]["user_id"] = user_id
            config["configurable"]["session_id"] = session_id
            if agent_key == "data_agent":
                config["configurable"].setdefault("analysis_id", task_id)
            config["configurable"]["thread_id"] = effective_thread_id

            config.setdefault("metadata", {})
            config["metadata"]["session_id"] = session_id
            config["metadata"]["thread_id"] = effective_thread_id
            config["metadata"]["request_id"] = request_id
            config["metadata"]["sub_agent"] = agent_key
            config["metadata"]["user_id"] = user_id

            config.setdefault("tags", [])
            if agent_key not in config["tags"]:
                config["tags"].append(agent_key)
            if "agent_platform" not in config["tags"]:
                config["tags"].append("agent_platform")
            if "async_task" not in config["tags"]:
                config["tags"].append("async_task")

            from langgraph.types import Command

            resume_input = Command(
                resume=[{"type": decision, "message": feedback}],
            )

            async for _chunk in graph.astream(resume_input, config=config):
                if await task_service.is_cancel_requested(UUID(task_id)):
                    await task_service.update_status(
                        UUID(task_id),
                        status="cancelled",
                        completed_at=datetime.utcnow(),
                    )
                    await emit_task_event(
                        "task_cancelled",
                        {"status": "cancelled", "progress": 100, "message": "已取消"},
                    )
                    await emit_job_event("job_cancelled", {"reason": "user_requested"})
                    return {"cancelled": True}

            interrupt_data = None
            try:
                state = await graph.aget_state(config)
                interrupt_data = extract_interrupt_data(state)
            except Exception:
                interrupt_data = None

            if interrupt_data:
                paused_result = {
                    "success": False,
                    "interrupted": True,
                    "interrupt_data": interrupt_data,
                    "audit_run_id": request_id,
                    "audit_url": f"/audit?q={request_id}",
                }
                await task_service.update_status(
                    UUID(task_id),
                    status="waiting_approval",
                    result=paused_result,
                )
                await task_service.update_progress(UUID(task_id), 90, "等待人工确认")
                await emit_task_event(
                    "task_waiting_approval",
                    {
                        "status": "waiting_approval",
                        "progress": 90,
                        "message": "等待人工确认",
                        "interrupt_data": interrupt_data,
                        "result": paused_result,
                    },
                )
                await emit_job_event("job_waiting_approval", {"interrupt_data": interrupt_data})
                return paused_result

            final_result = {
                "success": True,
                "audit_run_id": request_id,
                "audit_url": f"/audit?q={request_id}",
            }
            await task_service.update_status(
                UUID(task_id),
                status="completed",
                completed_at=datetime.utcnow(),
                result=final_result,
            )
            await task_service.update_progress(UUID(task_id), 100, "完成")
            await emit_task_event(
                "task_completed",
                {"status": "completed", "progress": 100, "message": "完成", "result": final_result},
            )
            await emit_job_event("job_completed", {"result": final_result})
            return final_result

        except Exception as e:
            _LOGGER.error(f"[Worker] Resume task {task_id} failed: {e}")
            await task_service.update_status(
                UUID(task_id),
                status="failed",
                completed_at=datetime.utcnow(),
                error=str(e),
            )
            await emit_task_event(
                "task_failed",
                {"status": "failed", "progress": 100, "message": "失败", "error": str(e)},
            )
            await emit_job_event(
                "job_failed",
                {
                    "error_class": type(e).__name__,
                    "error_message": str(e)[:2000],
                },
            )
            return {"error": str(e)}
        finally:
            try:
                await release_execute_concurrency(GovernanceKeys(tenant_id=tenant_id, user_id=user_id))
            except Exception:
                pass
            try:
                await event_bus.close()
            except Exception:
                pass
            if audit_redis is not None:
                try:
                    audit_redis.close()
                except Exception:
                    pass



# Global reference to keep task alive
_audit_worker_task = None
_audit_worker_instance = None

async def save_audit_log_to_db(events: Any):
    """Callback to persist audit event batch to Postgres using AuditPersistenceService."""
    from app.db import AsyncSessionLocal
    from app.services.audit_service import AuditPersistenceService
    from typing import List
    
    # Handle single event or batch
    if not isinstance(events, list):
        events = [events]
    
    try:
        async with AsyncSessionLocal() as db:
            service = AuditPersistenceService(db)
            await service.process_batch(events)
    except Exception as e:
        _LOGGER.error(f"Failed to persist audit log: {e}")


async def secrets_reencrypt_tenant(ctx: Dict[str, Any], tenant_id: str) -> Dict[str, Any]:
    """Background job: re-encrypt all secrets for a tenant to active key_ref."""
    from app.db import AsyncSessionLocal
    from app.services.secrets_service import SecretsService

    _LOGGER.info("[Worker] Re-encrypt tenant secrets start tenant_id=%s", tenant_id)
    async with AsyncSessionLocal() as db:
        result = await SecretsService(db).reencrypt_tenant_secrets(tenant_id=str(tenant_id))
        _LOGGER.info("[Worker] Re-encrypt tenant secrets done tenant_id=%s result=%s", tenant_id, result)
        return {
            "tenant_id": tenant_id,
            **result,
        }

async def startup(ctx: Dict[str, Any]):
    """Worker 启动钩子"""
    global _audit_worker_task, _audit_worker_instance
    print("DEBUG: [Worker] Startup hook called", flush=True)
    _LOGGER.info("Agent Worker starting...")
    
    # Initialize async checkpointer/store for LangGraph
    try:
        from agent_core.store import get_async_checkpointer, get_async_store
        await get_async_checkpointer()
        await get_async_store()
        _LOGGER.info("Async checkpointer and store initialized in worker.")
    except Exception as e:
        _LOGGER.error(f"Failed to init checkpointer/store in worker: {e}")
    
    # Start Audit Worker
    try:
        from agent_core.events import RedisEventBus
        from agent_core.settings import get_settings
        from agent_core.workers.audit import AuditWorker
        
        print("DEBUG: [Worker] Importing and initializing AuditWorker", flush=True)
        s = get_settings()
        bus = RedisEventBus(s.redis_url)
        # Pass the DB persistence callback
        worker = AuditWorker(bus, persist_callback=save_audit_log_to_db)
        
        _audit_worker_instance = worker
        # Run in background task
        loop = asyncio.get_running_loop()
        _audit_worker_task = loop.create_task(worker.start())
        print("DEBUG: [Worker] AuditWorker task created", flush=True)
        _LOGGER.info("AuditWorker background task started")
        
    except Exception as e:
        print(f"DEBUG: [Worker] Failed to start AuditWorker: {e}", flush=True)
        _LOGGER.error(f"Failed to start AuditWorker: {e}")


async def shutdown(ctx: Dict[str, Any]):
    """Worker 关闭钩子"""
    global _audit_worker_instance
    _LOGGER.info("Agent Worker shutting down...")
    
    if _audit_worker_instance:
        await _audit_worker_instance.stop()



class WorkerSettings:
    """ARQ Worker 配置"""
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    
    functions = [agent_execute_task, agent_resume_task, secrets_reencrypt_tenant]
    on_startup = startup
    on_shutdown = shutdown
    
    # 任务超时设置
    max_jobs = 10
    job_timeout = 3600  # 1 小时
    keep_result = 86400  # 结果保留 24 小时（可配置）

if __name__ == "__main__":
    import sys
    from arq import run_worker
    sys.exit(run_worker(WorkerSettings))
