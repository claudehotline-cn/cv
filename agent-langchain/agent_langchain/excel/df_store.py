from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import pandas as pd

from ..config import get_settings


@dataclass
class _DfEntry:
    df: pd.DataFrame
    session_id: str
    file_id: str
    sheet_name: str
    created_at: float
    last_access: float


class DataFrameStore:
    """进程内 DataFrame 缓存。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._df_by_id: Dict[str, _DfEntry] = {}
        self._key_to_id: Dict[Tuple[str, str, str], str] = {}
        self._seq: int = 0

    def _next_id(self) -> str:
        self._seq += 1
        return f"df_{self._seq}"

    def _make_key(self, session_id: str, file_id: str, sheet_name: Optional[str]) -> Tuple[str, str, str]:
        return (session_id, file_id, sheet_name or "")

    def _evict_if_needed(self) -> None:
        settings = get_settings()
        max_items = getattr(settings, "excel_df_cache_max_items", 16)
        ttl_sec = getattr(settings, "excel_df_cache_ttl_sec", 1800)
        now = time.time()

        expired_ids = [
            df_id
            for df_id, entry in self._df_by_id.items()
            if ttl_sec > 0 and (now - entry.last_access) > ttl_sec
        ]
        for df_id in expired_ids:
            entry = self._df_by_id.pop(df_id, None)
            if entry is None:
                continue
            key = self._make_key(entry.session_id, entry.file_id, entry.sheet_name)
            self._key_to_id.pop(key, None)

        if max_items > 0 and len(self._df_by_id) <= max_items:
            return

        if max_items <= 0:
            return

        sorted_items = sorted(self._df_by_id.items(), key=lambda kv: kv[1].last_access)
        for df_id, entry in sorted_items[:-max_items]:
            self._df_by_id.pop(df_id, None)
            key = self._make_key(entry.session_id, entry.file_id, entry.sheet_name)
            self._key_to_id.pop(key, None)

    def get_df(self, df_id: str) -> Optional[pd.DataFrame]:
        with self._lock:
            entry = self._df_by_id.get(df_id)
            if entry is None:
                return None
            entry.last_access = time.time()
            return entry.df

    def get_df_id(
        self,
        session_id: str,
        file_id: str,
        sheet_name: Optional[str],
    ) -> Optional[str]:
        key = self._make_key(session_id, file_id, sheet_name)
        with self._lock:
            df_id = self._key_to_id.get(key)
            if df_id is None:
                return None
            entry = self._df_by_id.get(df_id)
            if entry is None:
                self._key_to_id.pop(key, None)
                return None
            entry.last_access = time.time()
            return df_id

    def put_df(
        self,
        session_id: str,
        file_id: str,
        sheet_name: Optional[str],
        df: pd.DataFrame,
    ) -> str:
        key = self._make_key(session_id, file_id, sheet_name)
        now = time.time()
        with self._lock:
            existing_id = self._key_to_id.get(key)
            if existing_id is not None and existing_id in self._df_by_id:
                self._df_by_id[existing_id] = _DfEntry(
                    df=df,
                    session_id=session_id,
                    file_id=file_id,
                    sheet_name=key[2],
                    created_at=now,
                    last_access=now,
                )
                self._evict_if_needed()
                return existing_id

            df_id = self._next_id()
            self._df_by_id[df_id] = _DfEntry(
                df=df,
                session_id=session_id,
                file_id=file_id,
                sheet_name=key[2],
                created_at=now,
                last_access=now,
            )
            self._key_to_id[key] = df_id
            self._evict_if_needed()
            return df_id


_GLOBAL_DF_STORE: DataFrameStore | None = None


def get_df_store() -> DataFrameStore:
    """返回进程内单例 DataFrameStore。"""

    global _GLOBAL_DF_STORE
    if _GLOBAL_DF_STORE is None:
        _GLOBAL_DF_STORE = DataFrameStore()
    return _GLOBAL_DF_STORE

