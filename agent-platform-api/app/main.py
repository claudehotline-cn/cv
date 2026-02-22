import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# Configure global logging level
logging.basicConfig(level=logging.DEBUG)
logging.getLogger("uvicorn").setLevel(logging.INFO)  # Keep uvicorn less verbose
logging.getLogger("httpx").setLevel(logging.WARNING)  # Suppress httpx debug noise

from app.db import init_db, AsyncSessionLocal
from app.core.agent_registry import registry

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    print("Agent Platform API Starting...")
    await init_db()
    
    # Initialize async checkpointer/store for LangGraph
    from agent_core.store import get_async_checkpointer, get_async_store, cleanup_stores
    await get_async_checkpointer()
    await get_async_store()
    print("Async checkpointer and store initialized.")
    
    async with AsyncSessionLocal() as session:
        await registry.sync_plugins(session)
        
    # Initialize Global Event Bus
    from agent_core.events import RedisEventBus
    from agent_core.settings import get_settings
    settings = get_settings()
    app.state.event_bus = RedisEventBus(settings.redis_url)
    print("Global Redis Event Bus initialized.")
    
    yield
    # Shutdown
    await app.state.event_bus.close()
    await cleanup_stores()
    print("Agent Platform API Shutting down...")

app = FastAPI(
    title="Agent Platform API",
    description="Unified API for multi-agent system",
    version="1.0.0",
    lifespan=lifespan
)

from app.routes import agents, sessions, chat, tasks, audit, rag, auth, limits, secrets, agent_versions, prompts, eval

app.include_router(agents.router)
app.include_router(agent_versions.router)
app.include_router(sessions.router)
app.include_router(chat.router)
app.include_router(tasks.router)
app.include_router(audit.router)
app.include_router(rag.router)
app.include_router(auth.router)
app.include_router(limits.router)
app.include_router(limits.quota_router)
app.include_router(secrets.router)
app.include_router(prompts.router)
app.include_router(eval.router)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "version": "1.0.0"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
