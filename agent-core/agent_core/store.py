from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional
from .settings import get_settings

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    from langgraph.store.postgres.aio import AsyncPostgresStore

_LOGGER = logging.getLogger(__name__)

# Singleton instances
_checkpointer: Optional["AsyncPostgresSaver"] = None
_store: Optional["AsyncPostgresStore"] = None

# Context managers to keep connections alive
_checkpointer_cm = None
_store_cm = None


async def _init_async_postgres_checkpointer() -> "AsyncPostgresSaver":
    """Initialize async PostgresSaver (for async streaming)."""
    global _checkpointer_cm
    from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing AsyncPostgresSaver: %s", 
                 conn_string.replace(settings.postgres_password, "***"))
    
    # from_conn_string returns an async context manager
    _checkpointer_cm = AsyncPostgresSaver.from_conn_string(conn_string)
    checkpointer = await _checkpointer_cm.__aenter__()
    await checkpointer.setup()
    return checkpointer


async def _init_async_postgres_store() -> "AsyncPostgresStore":
    """Initialize async PostgresStore."""
    global _store_cm
    from langgraph.store.postgres.aio import AsyncPostgresStore
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing AsyncPostgresStore: %s",
                 conn_string.replace(settings.postgres_password, "***"))
    
    # from_conn_string returns an async context manager
    _store_cm = AsyncPostgresStore.from_conn_string(conn_string)
    store = await _store_cm.__aenter__()
    await store.setup()
    return store


async def get_async_checkpointer() -> "AsyncPostgresSaver":
    """Get or create the async checkpointer singleton."""
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = await _init_async_postgres_checkpointer()
    return _checkpointer


async def get_async_store() -> "AsyncPostgresStore":
    """Get or create the async store singleton."""
    global _store
    if _store is None:
        _store = await _init_async_postgres_store()
    return _store


async def cleanup_stores():
    """Cleanup store connections on shutdown."""
    global _checkpointer_cm, _store_cm
    if _checkpointer_cm:
        await _checkpointer_cm.__aexit__(None, None, None)
    if _store_cm:
        await _store_cm.__aexit__(None, None, None)


# Sync accessors for pre-initialized singletons (use after startup)
def get_checkpointer() -> "AsyncPostgresSaver":
    """Get the pre-initialized async checkpointer. Must call get_async_checkpointer() at startup first."""
    if _checkpointer is None:
        raise RuntimeError("Checkpointer not initialized. Call await get_async_checkpointer() at startup.")
    return _checkpointer


def get_store() -> "AsyncPostgresStore":
    """Get the pre-initialized async store. Must call get_async_store() at startup first."""
    if _store is None:
        raise RuntimeError("Store not initialized. Call await get_async_store() at startup.")
    return _store


# Legacy alias for backward compatibility
get_postgres_checkpointer = get_checkpointer
get_postgres_store = get_store
