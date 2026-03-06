import asyncio
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import DBAPIError, OperationalError

from app.api.routes_auth import router as auth_router
from app.api.routes_internal import router as internal_router
from app.api.routes_keys import router as keys_router
from app.core.config import get_settings
from app.core.db import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    last_error: Exception | None = None
    for attempt in range(10):
        try:
            await init_db()
            last_error = None
            break
        except OperationalError as exc:
            last_error = exc
            if attempt == 9:
                raise
            await asyncio.sleep(2)
    if last_error is not None:
        raise last_error
    yield


settings = get_settings()
app = FastAPI(title=settings.app_name, version=settings.app_version, lifespan=lifespan)
app.include_router(auth_router)
app.include_router(keys_router)
app.include_router(internal_router)


@app.exception_handler(OperationalError)
@app.exception_handler(DBAPIError)
async def handle_database_errors(_request: Request, _exc: Exception):
    return JSONResponse(
        status_code=503,
        content={"detail": "Authentication service database unavailable"},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}
