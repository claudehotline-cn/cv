"""article_agent 包：内容整理 Deep Agent for LangGraph。"""

from __future__ import annotations

import logging
import os


def _configure_logging() -> None:
    """根据环境变量配置 article_agent 日志级别。

    - 通过 ARTICLE_AGENT_LOG_LEVEL 控制日志级别（DEBUG/INFO/WARNING/ERROR），默认 INFO；
    - 仅在根 logger 尚未配置 handler 时调用 basicConfig，避免干扰外部应用的日志设置。
    """

    level_name = os.getenv("ARTICLE_AGENT_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    root_logger = logging.getLogger()
    if not root_logger.handlers:
        # 首次配置：直接使用 basicConfig。
        logging.basicConfig(
            level=level,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
    else:
        # 已有 handler（例如由 langgraph/宿主应用配置）时，提升根 logger 与各 handler 的级别，
        # 确保 ARTICLE_AGENT_LOG_LEVEL 能生效。
        root_logger.setLevel(level)
        for handler in root_logger.handlers:
            handler.setLevel(level)

    # 为 article_agent 包增加一个文件日志输出，默认写入 /logs/article-agent.log，
    # 以便在 docker-compose 映射的日志目录中查看调试信息。
    log_file = os.getenv("ARTICLE_AGENT_LOG_FILE", "/logs/article-agent.log")
    pkg_logger = logging.getLogger("article_agent")
    pkg_logger.setLevel(level)
    has_file_handler = any(
        isinstance(h, logging.FileHandler) and getattr(h, "baseFilename", None) == os.path.abspath(log_file)
        for h in pkg_logger.handlers
    )
    if not has_file_handler:
        try:
            fh = logging.FileHandler(log_file, encoding="utf-8")
            fh.setLevel(level)
            fh.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s"))
            pkg_logger.addHandler(fh)
        except Exception:
            # 文件日志配置失败时静默忽略，避免影响主流程。
            pass

    for name in (
        "article_agent",
        "article_agent.sub_agents",
        "article_agent.deep_graph",
        "article_agent.chat_graph",
        "article_agent.llm",
    ):
        logging.getLogger(name).setLevel(level)


_configure_logging()
