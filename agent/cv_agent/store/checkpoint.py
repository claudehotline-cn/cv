from functools import lru_cache
from typing import Any

from langgraph.checkpoint.memory import MemorySaver

from ..config import get_settings


@lru_cache(maxsize=1)
def get_checkpointer() -> Any:
    """
    返回当前配置下使用的 checkpoint 实现。

    - 默认：`memory` 使用 LangGraph 的 `MemorySaver`；
    - 当 `AGENT_CHECKPOINT_BACKEND=sqlite` 时：
      - 尝试导入 `langgraph.checkpoint.sqlite.SqliteSaver`；
      - 使用 `AGENT_CHECKPOINT_SQLITE_CONN` 或默认 `checkpoints.sqlite`；
      - 若导入失败则回退到 `MemorySaver` 并记录警告。

    MySQL 后端目前预留配置字段但未实现，使用时会抛出异常。
    """

    settings = get_settings()
    backend = (settings.checkpoint_backend or "memory").lower()

    if backend == "memory":
        return MemorySaver()

    if backend == "sqlite":
        try:
            # 依赖 langgraph-checkpoint-sqlite 额外包
            from langgraph.checkpoint.sqlite import SqliteSaver  # type: ignore[import]
        except Exception as exc:  # pragma: no cover - 环境缺少依赖时回退
            # 延迟导入失败时回退到内存模式，避免影响主流程
            import logging

            logging.getLogger("cv_agent").warning(
                "无法导入 SqliteSaver（%s），回退至 MemorySaver。"
                "如需启用 SQLite checkpoint，请在 agent 容器中安装 "
                "'langgraph-checkpoint-sqlite' 并重新启动。",
                exc,
            )
            return MemorySaver()

        conn_str = settings.checkpoint_sqlite_conn or "checkpoints.sqlite"
        return SqliteSaver.from_conn_string(conn_str)

    if backend == "mysql":
        # 预留：后续可接入 MySQL/Postgres 型 checkpoint 库
        raise RuntimeError(
            "AGENT_CHECKPOINT_BACKEND=mysql 尚未实现，请使用 memory 或 sqlite。"
        )

    # 未知后端：回退 memory
    import logging

    logging.getLogger("cv_agent").warning(
        "未知 checkpoint 后端 '%s'，回退至 MemorySaver。", backend
    )
    return MemorySaver()

