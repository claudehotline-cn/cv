from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.db_models import TenantModel, TenantMembershipModel


class TenantShadowService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure_tenant(self, tenant_id: str) -> UUID:
        tid = UUID(str(tenant_id))
        row = await self.db.scalar(select(TenantModel).where(TenantModel.id == tid))
        if row:
            return row.id

        tenant = TenantModel(id=tid, name=f"tenant-{str(tid)[:8]}", status="active")
        self.db.add(tenant)
        await self.db.commit()
        return tenant.id

    async def ensure_membership(self, tenant_id: UUID, user_id: str, role: str | None) -> None:
        if not user_id:
            return

        row = await self.db.scalar(
            select(TenantMembershipModel).where(
                TenantMembershipModel.tenant_id == tenant_id,
                TenantMembershipModel.user_id == user_id,
            )
        )
        normalized = "owner" if role == "admin" else "member"
        if row:
            changed = False
            if row.role != normalized:
                row.role = normalized
                changed = True
            if row.status != "active":
                row.status = "active"
                changed = True
            if changed:
                await self.db.commit()
            return

        self.db.add(
            TenantMembershipModel(
                tenant_id=tenant_id,
                user_id=user_id,
                role=normalized,
                status="active",
            )
        )
        await self.db.commit()

    async def has_active_membership(self, tenant_id: UUID, user_id: str) -> bool:
        if not user_id:
            return False
        row = await self.db.scalar(
            select(TenantMembershipModel).where(
                TenantMembershipModel.tenant_id == tenant_id,
                TenantMembershipModel.user_id == user_id,
                TenantMembershipModel.status == "active",
            )
        )
        return row is not None
