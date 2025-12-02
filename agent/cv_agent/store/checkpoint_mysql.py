from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence

import pymysql
from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_serializable_checkpoint_metadata,
)

logger = logging.getLogger("cv_agent")


@dataclass
class _CheckpointRow:
    """Internal representation of one checkpoint row."""

    thread_id: str
    checkpoint_ns: str
    payload: Dict[str, Any]
    version: int


class MySQLCheckpointStore:
    """
    MySQL-backed storage for LangGraph checkpoints.

    Schema (see `db/schema.sql`):

        CREATE TABLE IF NOT EXISTS agent_checkpoints (
          id            BIGINT AUTO_INCREMENT PRIMARY KEY,
          thread_id     VARCHAR(255) NOT NULL,
          checkpoint_ns VARCHAR(255) NOT NULL,
          checkpoint    JSON NOT NULL,
          version       INT NOT NULL DEFAULT 1,
          created_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
          updated_at    DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
          INDEX idx_agent_chk_thread_ns (thread_id, checkpoint_ns),
          INDEX idx_agent_chk_updated   (updated_at),
          CHECK (JSON_VALID(`checkpoint`))
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

    其中 `checkpoint` 字段存储一个 JSON 对象，内部包含：
    - checkpoint: 通过 LangGraph serde 编码的 Checkpoint；
    - metadata: 通过 serde 编码的 CheckpointMetadata；
    - parent_config: 上一个 checkpoint 的配置（若存在）；
    - pending_writes: 通过 serde 编码的 pending writes 列表。
    """

    def __init__(self, dsn: str) -> None:
        """
        DSN 格式：mysql+pymysql://user:pass@host:port/dbname
        """

        if not dsn.startswith("mysql"):
            raise ValueError(f"Unsupported MySQL DSN: {dsn!r}")

        # Example: mysql+pymysql://root:123456@mysql:3306/cv_cp
        without_scheme = dsn.split("://", 1)[1]
        auth_and_host, _, db_part = without_scheme.partition("/")
        user_part, _, host_part = auth_and_host.partition("@")
        username, _, password = user_part.partition(":")
        host, _, port_str = host_part.partition(":")

        self._db = db_part or "cv_agent"
        self._user = username or "root"
        self._password = password or ""
        self._host = host or "mysql"
        self._port = int(port_str or "3306")

        logger.info(
            "MySQLCheckpointStore initialized for host=%s port=%s db=%s",
            self._host,
            self._port,
            self._db,
        )

    # ---- low-level helpers -------------------------------------------------

    def _connect(self) -> Any:
        return pymysql.connect(
            host=self._host,
            port=self._port,
            user=self._user,
            password=self._password,
            database=self._db,
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )

    # ---- public API --------------------------------------------------------

    def get_latest(self, *, thread_id: str, namespace: str) -> Optional[_CheckpointRow]:
        """Return latest checkpoint record for (thread_id, namespace)."""

        sql = (
            "SELECT thread_id, checkpoint_ns, checkpoint, version "
            "FROM agent_checkpoints "
            "WHERE thread_id=%s AND checkpoint_ns=%s "
            "ORDER BY updated_at DESC, id DESC "
            "LIMIT 1"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (thread_id, namespace))
                row = cur.fetchone()
        if not row:
            return None
        payload = row["checkpoint"]
        if isinstance(payload, str):
            payload = json.loads(payload)
        return _CheckpointRow(
            thread_id=row["thread_id"],
            checkpoint_ns=row["checkpoint_ns"],
            payload=payload,
            version=row.get("version", 1),
        )

    def put(
        self,
        *,
        thread_id: str,
        namespace: str,
        payload: Dict[str, Any],
        version: int = 1,
    ) -> None:
        """Insert or replace the checkpoint record for (thread_id, namespace)."""

        sql_delete = (
            "DELETE FROM agent_checkpoints WHERE thread_id=%s AND checkpoint_ns=%s"
        )
        sql_insert = (
            "INSERT INTO agent_checkpoints "
            "(thread_id, checkpoint_ns, checkpoint, version) "
            "VALUES (%s, %s, %s, %s)"
        )
        data = json.dumps(payload, ensure_ascii=False)
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql_delete, (thread_id, namespace))
                cur.execute(sql_insert, (thread_id, namespace, data, version))

    def delete_thread(self, thread_id: str) -> None:
        """Delete all checkpoints for a given thread."""

        sql = "DELETE FROM agent_checkpoints WHERE thread_id=%s"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (thread_id,))

    def list_threads(self, *, namespace: str, limit: int = 50) -> Iterable[str]:
        """List distinct thread_ids that have checkpoints in given namespace."""

        sql = (
            "SELECT thread_id "
            "FROM agent_checkpoints "
            "WHERE checkpoint_ns=%s "
            "GROUP BY thread_id "
            "ORDER BY MAX(updated_at) DESC "
            "LIMIT %s"
        )
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, (namespace, int(limit)))
                rows = cur.fetchall()
        for row in rows:
            yield row["thread_id"]


class MySQLSaver(BaseCheckpointSaver[str]):
    """
    基于 MySQL 的 LangGraph CheckpointSaver 实现。

    特性（当前版本）：
    - 按 (thread_id, checkpoint_ns) 维度仅保存「最新」一个 checkpoint；
    - 通过 JsonPlusSerializer 将 Checkpoint / Metadata / pending_writes 编码为 JSON 存储；
    - 实现 BaseCheckpointSaver 同步/异步接口，以支持 create_react_agent / StateGraph。
    """

    def __init__(
        self,
        store: MySQLCheckpointStore,
        *,
        serde: Optional[Any] = None,
    ) -> None:
        super().__init__(serde=serde)
        self._store = store

    # Factory-style constructor for use in config
    @classmethod
    def from_dsn(cls, dsn: str) -> "MySQLSaver":
        store = MySQLCheckpointStore(dsn)
        return cls(store)

    # ---- helpers: typed <-> JSON ------------------------------------------

    def _encode_typed(self, obj: Any) -> Dict[str, str]:
        t, data = self.serde.dumps_typed(obj)
        return {
            "type": t,
            "b64": base64.b64encode(data).decode("ascii"),
        }

    def _decode_typed(self, payload: Dict[str, str]) -> Any:
        t = payload.get("type", "null")
        b64 = payload.get("b64", "")
        raw = base64.b64decode(b64.encode("ascii")) if b64 else b""
        return self.serde.loads_typed((t, raw))

    # ---- BaseCheckpointSaver sync API -------------------------------------

    def get_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        cfg = config.get("configurable") or {}
        thread_id = cfg.get("thread_id")
        if not thread_id:
            return None
        checkpoint_ns = cfg.get("checkpoint_ns", "")

        row = self._store.get_latest(thread_id=str(thread_id), namespace=checkpoint_ns)
        if row is None:
            return None

        payload = row.payload or {}
        cp_enc = payload.get("checkpoint")
        md_enc = payload.get("metadata")
        pw_enc = payload.get("pending_writes")
        parent_config = payload.get("parent_config")

        if not cp_enc or not md_enc:
            return None

        checkpoint: Checkpoint = self._decode_typed(cp_enc)
        metadata: CheckpointMetadata = self._decode_typed(md_enc)
        pending_writes: List[Any] = (
            self._decode_typed(pw_enc) if pw_enc is not None else []
        )

        # 统一返回带 checkpoint_id 的配置，便于后续 put_writes / list 等使用
        checkpoint_id = checkpoint.get("id")
        out_config: RunnableConfig = {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

        return CheckpointTuple(
            config=out_config,
            checkpoint=checkpoint,
            metadata=metadata,
            parent_config=parent_config,
            pending_writes=pending_writes,
        )

    def list(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterator[CheckpointTuple]:
        """
        当前实现为简化版：
        - 若提供 config，则仅返回该线程在对应 namespace 下的最新 checkpoint（若存在）；
        - filter/before/limit 仅作最小支持：limit<=0 时不返回，filter 仅精确匹配 metadata 键值。
        """

        if limit is not None and limit <= 0:
            return iter(())

        if not config:
            # 简化：不支持无 config 列表，保持行为可预期
            return iter(())

        value = self.get_tuple(config)
        if value is None:
            return iter(())

        if filter:
            md = value.metadata
            if not all(md.get(k) == v for k, v in filter.items()):
                return iter(())

        # 忽略 before：当前仅保存最新 checkpoint
        return iter([value])

    def put(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        cfg = config.get("configurable") or {}
        thread_id = cfg.get("thread_id")
        if not thread_id:
            raise ValueError("MySQLSaver.put requires config['configurable']['thread_id']")
        checkpoint_ns = cfg.get("checkpoint_ns", "")

        parent_id = get_checkpoint_id(config)
        parent_config: Optional[RunnableConfig]
        if parent_id:
            parent_config = {
                "configurable": {
                    "thread_id": thread_id,
                    "checkpoint_ns": checkpoint_ns,
                    "checkpoint_id": parent_id,
                }
            }
        else:
            parent_config = None

        # 统一处理 metadata（剔除内部字段）
        serialized_metadata = get_serializable_checkpoint_metadata(config, metadata)

        # pending_writes 在 put_writes 中更新，这里初始化为空列表
        payload: Dict[str, Any] = {
            "checkpoint": self._encode_typed(checkpoint),
            "metadata": self._encode_typed(serialized_metadata),
            "parent_config": parent_config,
            "pending_writes": self._encode_typed([]),
        }

        self._store.put(
            thread_id=str(thread_id),
            namespace=checkpoint_ns,
            payload=payload,
            version=1,
        )

        checkpoint_id = checkpoint.get("id")
        return {
            "configurable": {
                "thread_id": thread_id,
                "checkpoint_ns": checkpoint_ns,
                "checkpoint_id": checkpoint_id,
            }
        }

    def put_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        cfg = config.get("configurable") or {}
        thread_id = cfg.get("thread_id")
        if not thread_id:
            return
        checkpoint_ns = cfg.get("checkpoint_ns", "")

        row = self._store.get_latest(thread_id=str(thread_id), namespace=checkpoint_ns)
        if row is None:
            return

        payload = dict(row.payload or {})
        existing: List[Any] = []
        if "pending_writes" in payload and payload["pending_writes"] is not None:
            try:
                existing = list(self._decode_typed(payload["pending_writes"]))
            except Exception:  # pragma: no cover - 容错
                existing = []

        # PendingWrite = (task_id, channel, value)
        new_items = [(task_id, channel, value) for channel, value in writes]
        all_items = existing + new_items

        payload["pending_writes"] = self._encode_typed(all_items)
        self._store.put(
            thread_id=str(thread_id),
            namespace=checkpoint_ns,
            payload=payload,
            version=row.version,
        )

    def delete_thread(self, thread_id: str) -> None:
        self._store.delete_thread(thread_id)

    # ---- BaseCheckpointSaver async API ------------------------------------

    async def aget_tuple(self, config: RunnableConfig) -> Optional[CheckpointTuple]:
        return self.get_tuple(config)

    async def alist(
        self,
        config: Optional[RunnableConfig],
        *,
        filter: Optional[Dict[str, Any]] = None,
        before: Optional[RunnableConfig] = None,
        limit: Optional[int] = None,
    ) -> Iterable[CheckpointTuple]:
        return self.list(config, filter=filter, before=before, limit=limit)

    async def aput(
        self,
        config: RunnableConfig,
        checkpoint: Checkpoint,
        metadata: CheckpointMetadata,
        new_versions: ChannelVersions,
    ) -> RunnableConfig:
        return self.put(config, checkpoint, metadata, new_versions)

    async def aput_writes(
        self,
        config: RunnableConfig,
        writes: Sequence[tuple[str, Any]],
        task_id: str,
        task_path: str = "",
    ) -> None:
        self.put_writes(config, writes, task_id, task_path)

    async def adelete_thread(self, thread_id: str) -> None:
        self.delete_thread(thread_id)
