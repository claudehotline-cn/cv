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


async def agent_execute_task(
    ctx: Dict[str, Any],
    task_id: str,
    session_id: str,
    agent_key: str,
    input_message: str,
    config: Dict[str, Any] = None
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
    redis: ArqRedis = ctx.get("redis")
    
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
            
            async for chunk in graph.astream(
                {"messages": [{"role": "user", "content": input_message}]},
                config=config or {}
            ):
                result_chunks.append(chunk)
                
                # 更新进度（简单递增）
                progress = min(90, progress + 5)
                await task_service.update_progress(UUID(task_id), progress, "执行中...")
                
                # 发布到 Redis Stream 供前端 SSE 消费
                if redis:
                    await redis.xadd(
                        f"task:{task_id}:stream",
                        {"type": "chunk", "data": str(chunk)[:1000]},
                        maxlen=1000
                    )
                
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


async def startup(ctx: Dict[str, Any]):
    """Worker 启动钩子"""
    _LOGGER.info("Agent Worker starting...")


async def shutdown(ctx: Dict[str, Any]):
    """Worker 关闭钩子"""
    _LOGGER.info("Agent Worker shutting down...")


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
