from typing import Any, List

from .pipelines import (
    delete_pipeline_tool,
    drain_pipeline_tool,
    get_pipeline_status_tool,
    hotswap_model_tool,
    list_pipelines_tool,
    plan_delete_pipeline_tool,
    plan_drain_pipeline_tool,
    plan_hotswap_model_tool,
    plan_update_pipeline_config_tool,
)
from .rag import search_cv_docs_tool
from .registry import (
    TOOL_REGISTRY,
    list_registered_tools,
    register_tool,
)

# 在模块导入阶段注册已有工具及其元数据
register_tool(list_pipelines_tool, read_only=True, high_risk=False, domain="pipeline")
register_tool(get_pipeline_status_tool, read_only=True, high_risk=False, domain="pipeline")
register_tool(
    plan_update_pipeline_config_tool,
    read_only=True,
    high_risk=False,
    domain="pipeline",
)
register_tool(
    plan_delete_pipeline_tool,
    read_only=True,
    high_risk=False,
    domain="pipeline",
)
register_tool(
    delete_pipeline_tool,
    read_only=False,
    high_risk=True,
    domain="pipeline",
)
register_tool(
    plan_hotswap_model_tool,
    read_only=True,
    high_risk=False,
    domain="pipeline",
)
register_tool(
    hotswap_model_tool,
    read_only=False,
    high_risk=True,
    domain="pipeline",
)
register_tool(
    plan_drain_pipeline_tool,
    read_only=True,
    high_risk=False,
    domain="pipeline",
)
register_tool(
    drain_pipeline_tool,
    read_only=False,
    high_risk=True,
    domain="pipeline",
)
register_tool(
    search_cv_docs_tool,
    read_only=True,
    high_risk=False,
    domain="knowledge",
)

__all__ = [
    "list_pipelines_tool",
    "get_pipeline_status_tool",
    "plan_update_pipeline_config_tool",
    "plan_delete_pipeline_tool",
    "delete_pipeline_tool",
    "plan_hotswap_model_tool",
    "hotswap_model_tool",
    "plan_drain_pipeline_tool",
    "drain_pipeline_tool",
    "search_cv_docs_tool",
    "TOOL_REGISTRY",
    "get_all_tools",
]


def get_all_tools() -> List[Any]:
    """Return the list of tools registered for the control-plane agent."""

    return list_registered_tools()
