from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from .settings import get_settings

if TYPE_CHECKING:
    from langgraph.checkpoint.postgres import PostgresSaver
    from langgraph.store.postgres import PostgresStore

_LOGGER = logging.getLogger(__name__)

_checkpointer: "PostgresSaver | None" = None
_store: "PostgresStore | None" = None


def _init_postgres_checkpointer() -> "PostgresSaver":
    from langgraph.checkpoint.postgres import PostgresSaver
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing PostgresSaver: %s", 
                 conn_string.replace(settings.postgres_password, "***"))
    
    cm = PostgresSaver.from_conn_string(conn_string)
    saver = cm.__enter__()
    saver.setup()
    return saver


def _init_postgres_store() -> "PostgresStore":
    from langgraph.store.postgres import PostgresStore
    
    settings = get_settings()
    conn_string = settings.postgres_uri
    
    _LOGGER.info("Initializing PostgresStore: %s",
                 conn_string.replace(settings.postgres_password, "***"))
    
    cm = PostgresStore.from_conn_string(conn_string)
    store = cm.__enter__()
    store.setup()
    return store


def get_postgres_checkpointer() -> "PostgresSaver":
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = _init_postgres_checkpointer()
    return _checkpointer


def get_postgres_store() -> "PostgresStore":
    global _store
    if _store is None:
        _store = _init_postgres_store()
    return _store
