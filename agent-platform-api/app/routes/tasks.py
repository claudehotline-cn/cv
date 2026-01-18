"""异步任务 API 路由"""

import asyncio
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
import redis.asyncio as aioredis

from ..db import get_db
from ..services.task_service import TaskService
from ..models.db_models import SessionModel
from agent_core.settings import get_settings

router = APIRouter(prefix="/tasks", tags=["tasks"])
settings = get_settings()


class ExecuteRequest(BaseModel):
    """执行任务请求"""
    message: str
    config: Optional[dict] = None


class TaskResponse(BaseModel):
    """任务响应"""
    id: str
    session_id: str
    status: str
    progress: int
    progress_message: Optional[str] = None
    result: Optional[dict] = None
    error: Optional[str] = None


@router.post("/sessions/{session_id}/execute")
async def create_execute_task(
    session_id: UUID,
    request: ExecuteRequest,
    db: AsyncSession = Depends(get_db)
):
    """创建异步执行任务"""
    from sqlalchemy import select
    from arq import create_pool
    from arq.connections import RedisSettings
    
    # 验证 session 存在
    result = await db.execute(
        select(SessionModel).where(SessionModel.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # 获取 agent_key
    from ..models.db_models import AgentModel
    agent_result = await db.execute(
        select(AgentModel).where(AgentModel.id == session.agent_id)
    )
    agent = agent_result.scalar_one_or_none()
    agent_key = agent.builtin_key if agent else "data_agent"
    
    # 创建任务记录
    task_service = TaskService(db)
    task = await task_service.create_task(session_id)
    
    # 入队 ARQ 任务
    redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await redis_pool.enqueue_job(
        "agent_execute_task",
        str(task.id),
        str(session_id),
        agent_key,
        request.message,
        request.config
    )
    await redis_pool.close()
    
    return {
        "task_id": str(task.id),
        "status": "pending",
        "message": "Task queued for execution"
    }


@router.get("/{task_id}")
async def get_task_status(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """获取任务状态"""
    task_service = TaskService(db)
    task = await task_service.get_task(task_id)
    
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskResponse(
        id=str(task.id),
        session_id=str(task.session_id),
        status=task.status,
        progress=task.progress,
        progress_message=task.progress_message,
        result=task.result,
        error=task.error
    )


@router.post("/{task_id}/cancel")
async def cancel_task(
    task_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """请求取消任务"""
    task_service = TaskService(db)
    success = await task_service.request_cancel(task_id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Cannot cancel task (not found or already completed)"
        )
    
    return {"message": "Cancel requested", "task_id": str(task_id)}


@router.get("/{task_id}/stream")
async def stream_task_progress(task_id: UUID):
    """SSE 流式获取任务进度"""
    
    async def event_generator():
        redis = aioredis.from_url(settings.redis_url)
        stream_key = f"task:{task_id}:stream"
        last_id = "0"
        
        try:
            while True:
                # 读取 Redis Stream
                messages = await redis.xread(
                    {stream_key: last_id},
                    count=10,
                    block=1000  # 阻塞 1 秒
                )
                
                if messages:
                    for stream_name, entries in messages:
                        for entry_id, data in entries:
                            last_id = entry_id
                            event_data = {
                                "type": data.get(b"type", b"").decode(),
                                "data": data.get(b"data", b"").decode()
                            }
                            yield f"data: {json.dumps(event_data)}\n\n"
                
                # 检查任务是否完成
                # 简化处理：前端通过 status 端点主动查询最终状态
                await asyncio.sleep(0.1)
                
        except asyncio.CancelledError:
            pass
        finally:
            await redis.close()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )
