"""任务服务层 - 管理异步任务的创建、查询、更新"""

from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import TaskModel


class TaskService:
    """异步任务服务"""
    
    def __init__(self, db: AsyncSession):
        self.db = db
    
    async def create_task(self, session_id: UUID) -> TaskModel:
        """创建新任务"""
        task = TaskModel(session_id=session_id, status="pending")
        self.db.add(task)
        await self.db.commit()
        await self.db.refresh(task)
        return task
    
    async def get_task(self, task_id: UUID) -> Optional[TaskModel]:
        """获取任务"""
        result = await self.db.execute(
            select(TaskModel).where(TaskModel.id == task_id)
        )
        return result.scalar_one_or_none()
    
    async def get_tasks_by_session(self, session_id: UUID) -> list[TaskModel]:
        """获取会话的所有任务"""
        result = await self.db.execute(
            select(TaskModel)
            .where(TaskModel.session_id == session_id)
            .order_by(TaskModel.created_at.desc())
        )
        return list(result.scalars().all())
    
    async def update_status(
        self, 
        task_id: UUID, 
        status: str,
        started_at: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        error: Optional[str] = None,
        result: Optional[Dict[str, Any]] = None
    ) -> None:
        """更新任务状态"""
        values = {"status": status}
        if started_at:
            values["started_at"] = started_at
        if completed_at:
            values["completed_at"] = completed_at
        if error:
            values["error"] = error
        if result:
            values["result"] = result
            
        await self.db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(**values)
        )
        await self.db.commit()
    
    async def update_progress(
        self, 
        task_id: UUID, 
        progress: int, 
        message: Optional[str] = None
    ) -> None:
        """更新任务进度"""
        values = {"progress": min(100, max(0, progress))}
        if message:
            values["progress_message"] = message
            
        await self.db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(**values)
        )
        await self.db.commit()
    
    async def request_cancel(self, task_id: UUID) -> bool:
        """请求取消任务"""
        task = await self.get_task(task_id)
        if not task:
            return False
        if task.status in ("completed", "failed", "cancelled"):
            return False
        
        await self.db.execute(
            update(TaskModel)
            .where(TaskModel.id == task_id)
            .values(cancel_requested=True)
        )
        await self.db.commit()
        return True
    
    async def is_cancel_requested(self, task_id: UUID) -> bool:
        """检查是否请求了取消"""
        task = await self.get_task(task_id)
        return task.cancel_requested if task else False
