"""ARQ Worker 配置和任务函数"""

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict
from uuid import UUID

from arq import ArqRedis
from arq.connections import RedisSettings

from agent_core.settings import get_settings

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
    user_id: str = "default"
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
    from app.db import async_session_maker
    from app.services.task_service import TaskService
    from app.core.plugin_loader import get_agent_class
    
    _LOGGER.info(f"[Worker] Starting task {task_id} for agent {agent_key}")
    
    # Init EventBus
    from agent_core.events import RedisEventBus
    event_bus = RedisEventBus(settings.redis_url)
    
    async with async_session_maker() as db:
        task_service = TaskService(db)
        
        # 更新状态为 running
        await task_service.update_status(
            UUID(task_id), 
            status="running", 
            started_at=datetime.utcnow()
        )
        await task_service.update_progress(UUID(task_id), 10, "正在初始化 Agent...")
        
        try:
            # 加载 Agent
            agent_class = get_agent_class(agent_key)
            if not agent_class:
                raise ValueError(f"Agent not found: {agent_key}")
            
            agent = agent_class()
            graph = agent.get_graph()
            
            await task_service.update_progress(UUID(task_id), 20, "Agent 已加载，开始执行...")
            
            # 检查取消
            if await task_service.is_cancel_requested(UUID(task_id)):
                await task_service.update_status(
                    UUID(task_id), 
                    status="cancelled",
                    completed_at=datetime.utcnow()
                )
                return {"cancelled": True}
            
            # 执行 Agent（流式）
            result_chunks = []
            progress = 20
            
            # Inject task_id and user_id into config
            config = config or {}
            config.setdefault("configurable", {})
            config["configurable"]["task_id"] = task_id
            config["configurable"]["user_id"] = user_id

            async for chunk in graph.astream(
                {"messages": [{"role": "user", "content": input_message}]},
                config=config
            ):
                result_chunks.append(chunk)
                
                # 更新进度（简单递增）
                progress = min(90, progress + 5)
                await task_service.update_progress(UUID(task_id), progress, "执行中...")
                
                # 发布到 Redis Stream (Event Bus)
                await event_bus.publish(f"task:{task_id}:stream", {
                    "type": "chunk", 
                    "data": str(chunk)[:1000]
                })
                
                # 检查取消
                if await task_service.is_cancel_requested(UUID(task_id)):
                    await task_service.update_status(
                        UUID(task_id), 
                        status="cancelled",
                        completed_at=datetime.utcnow()
                    )
                    return {"cancelled": True, "partial_result": result_chunks}
            
            # 完成
            final_result = {"chunks": len(result_chunks), "success": True}
            await task_service.update_status(
                UUID(task_id),
                status="completed",
                completed_at=datetime.utcnow(),
                result=final_result
            )
            await task_service.update_progress(UUID(task_id), 100, "完成")
            
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
            return {"error": str(e)}
        finally:
            await event_bus.close()



# Global reference to keep task alive
_audit_worker_task = None
_audit_worker_instance = None

async def save_audit_log_to_db(event: Dict[str, Any]):
    """Callback to persist audit event to Postgres."""
    from app.db import AsyncSessionLocal
    from app.models.db_models import AuditLogModel
    
    try:
        async with AsyncSessionLocal() as db:
            log = AuditLogModel(
                event_type=event.get("type", "unknown"),
                user_id=str(event.get("user_id", "")),
                trace_id=str(event.get("trace_id", "")),
                task_id=str(event.get("task_id", "")), # May be missing
                data=event # Store full event as JSONB
            )
            db.add(log)
            await db.commit()
    except Exception as e:
        _LOGGER.error(f"Failed to persist audit log: {e}")

async def startup(ctx: Dict[str, Any]):
    """Worker 启动钩子"""
    global _audit_worker_task, _audit_worker_instance
    print("DEBUG: [Worker] Startup hook called", flush=True)
    _LOGGER.info("Agent Worker starting...")
    
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
    
    functions = [agent_execute_task]
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
