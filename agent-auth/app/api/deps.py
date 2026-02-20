from fastapi import Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.domain.value_objects.principal import Principal
from app.infrastructure.wiring.container import Container


async def get_container(session: AsyncSession = Depends(get_db)) -> Container:
    return Container(session)


def _extract_bearer(authorization: str | None) -> str:
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization header")
    if not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Invalid Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(status_code=401, detail="Empty token")
    return token


async def get_current_principal(
    authorization: str | None = Header(default=None),
    container: Container = Depends(get_container),
) -> Principal:
    token = _extract_bearer(authorization)
    try:
        return container.token_verifier.verify_access(token)
    except Exception as exc:
        raise HTTPException(status_code=401, detail="Invalid token") from exc


async def require_admin(principal: Principal = Depends(get_current_principal)) -> Principal:
    if principal.role != "admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return principal
