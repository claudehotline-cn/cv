"""异步任务 API 路由"""

import asyncio
import json
from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

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


class TaskListResponse(BaseModel):
    """会话任务列表响应"""

    session_id: str
    tasks: list[TaskResponse]


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
    task = await task_service.create_task(
        session_id,
        meta={
            "input_message": request.message,
            "agent_key": agent_key,
            "thread_id": str(session.thread_id) if session.thread_id else str(session_id),
        },
    )
    
    # 入队 ARQ 任务
    redis_pool = await create_pool(RedisSettings.from_dsn(settings.redis_url))
    await redis_pool.enqueue_job(
        "agent_execute_task",
        str(task.id),
        str(session_id),
        agent_key,
        request.message,
        request.config,
        "default", # user_id
        str(session.thread_id) if session.thread_id else str(session_id) # thread_id (new arg)
    )
    await redis_pool.close()
    
    return {
        "task_id": str(task.id),
        "status": "pending",
        "message": "Task queued for execution"
    }


@router.get("/sessions/{session_id}", response_model=TaskListResponse)
async def list_session_tasks(
    session_id: UUID,
    status: Optional[str] = Query(
        default=None,
        description="Filter by task status. Use 'active' for pending/running tasks.",
    ),
    limit: int = Query(default=50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
):
    """获取会话的任务列表（用于页面返回后恢复任务状态）。"""
    from sqlalchemy import select

    # 验证 session 存在
    result = await db.execute(select(SessionModel).where(SessionModel.id == session_id))
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    task_service = TaskService(db)
    tasks = await task_service.get_tasks_by_session(session_id)

    if status == "active":
        tasks = [t for t in tasks if t.status in ("pending", "running")]
    elif status:
        tasks = [t for t in tasks if t.status == status]

    tasks = tasks[:limit]

    return TaskListResponse(
        session_id=str(session_id),
        tasks=[
            TaskResponse(
                id=str(t.id),
                session_id=str(t.session_id),
                status=t.status,
                progress=t.progress,
                progress_message=t.progress_message,
                result=t.result,
                error=t.error,
            )
            for t in tasks
        ],
    )


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
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")

    success = await task_service.request_cancel(task_id)
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail="Cannot cancel task (not found or already completed)"
        )

    # Emit cancel-requested event for realtime UI (worker will later emit cancelled)
    from agent_core.events import RedisEventBus
    event_bus = RedisEventBus(settings.redis_url)
    try:
        event = {
            "type": "task_cancel_requested",
            "task_id": str(task_id),
            "session_id": str(task.session_id),
            "status": task.status,
            "message": "取消请求已提交",
        }
        await event_bus.publish(f"task:{task_id}:stream", event)
        await event_bus.publish(f"session:{task.session_id}:tasks", event)
    finally:
        await event_bus.close()
    
    return {"message": "Cancel requested", "task_id": str(task_id)}


@router.get("/sessions/{session_id}/stream")
async def stream_session_task_events(session_id: UUID, request: Request):
    """SSE：订阅某个会话下所有任务的事件流（进度/状态/结果）。"""

    async def event_generator():
        from agent_core.events import RedisEventBus

        event_bus = RedisEventBus(settings.redis_url)
        stream_key = f"session:{session_id}:tasks"

        try:
            async for event in event_bus.subscribe(stream_key):
                # RedisEventBus yields dicts directly
                yield f"data: {json.dumps(event)}\n\n"

                # Let FastAPI cancel when client disconnects
                if await request.is_disconnected():
                    break
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.close()

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/{task_id}/stream")
async def stream_task_progress(task_id: UUID, request: Request):
    """SSE 流式获取任务进度"""
    
    async def event_generator():

        from agent_core.events import RedisEventBus
        event_bus = RedisEventBus(settings.redis_url)
        stream_key = f"task:{task_id}:stream"
        
        try:
            async for event in event_bus.subscribe(stream_key):
                # RedisEventBus yields dicts directly
                # Ensure type and data structure matches frontend expectation
                # Existing frontend expects: {"type": ..., "data": ...}
                yield f"data: {json.dumps(event)}\n\n"
                
                # Check for completion via DB or event type?
                # For now infinite stream or until client disconnect
                if await request.is_disconnected():
                    break
                
        except asyncio.CancelledError:
            pass
        finally:
            await event_bus.close()
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no"
        }
    )


@router.get("/threads/{thread_id}/history")
async def get_thread_history(thread_id: str, limit: int = 10, before: Optional[str] = None):
    """
    Get state history (checkpoints) for a thread.
    Useful for visualizing the timeline to pick a rollback point.
    """
    from agent_core.store import get_async_checkpointer
    
    checkpointer = await get_async_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    
    checkpoints = []
    # Note: list method returns an AsyncIterator
    async for cp in checkpointer.list(config, limit=limit, before=before):
        checkpoints.append({
            "checkpoint_id": cp.checkpoint_id,
            "checkpoint_ts": cp.checkpoint.get("ts") if cp.checkpoint else None,
            "parent_checkpoint_id": cp.checkpoint.get("channel_values", {}).get("parent_id") if cp.checkpoint else None,
            "metadata": cp.metadata
        })
        
    return {"checkpoints": checkpoints}


class RollbackRequest(BaseModel):
    checkpoint_id: str


@router.post("/threads/{thread_id}/rollback")
async def rollback_thread_state(thread_id: str, request: RollbackRequest):
    """
    Rollback thread state to a specific checkpoint.
    """
    from agent_core.store import get_async_checkpointer
    
    checkpointer = await get_async_checkpointer()
    config = {"configurable": {"thread_id": thread_id}}
    
    # Verify checkpoint exists
    target_cp = await checkpointer.get_tuple(config, checkpoint_id=request.checkpoint_id)
    if not target_cp:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    
    # In LangGraph/DeepAgents architecture, rolling back essentially means 
    # ensuring the NEXT run starts from this checkpoint.
    # The Frontend/Client should use this checkpoint_id in the next execution config.
    # We validate it here and return confirmation.
    
    return {
        "message": "Checkpoint validated. Use this checkpoint_id in next execution config to fork.",
        "checkpoint": {
            "id": request.checkpoint_id,
            "ts": target_cp.checkpoint.get("ts") if target_cp.checkpoint else None
        }
    }
