from typing import Any, Dict, List, Optional


class ToolRegistry:
    """
    简单的工具注册表，用于统一管理 Agent 可用的工具及其元数据。

    元数据示例：
    - read_only: 只读工具（多次调用安全）；
    - high_risk: 高危写操作（需要 plan + confirm 流程保护）；
    - domain: 归属的业务域（pipeline/va/debug/metrics/...），便于后续按域过滤。
    """

    def __init__(self) -> None:
        self._tools: Dict[str, Dict[str, Any]] = {}

    def register(
        self,
        tool: Any,
        *,
        name: Optional[str] = None,
        read_only: bool = True,
        high_risk: bool = False,
        domain: str = "generic",
    ) -> None:
        tool_name = (
            name
            or getattr(tool, "name", None)
            or getattr(tool, "__name__", None)
            or repr(tool)
        )
        self._tools[tool_name] = {
            "tool": tool,
            "read_only": read_only,
            "high_risk": high_risk,
            "domain": domain,
        }

    def list_tools(
        self,
        *,
        include_high_risk: bool = True,
        domain: Optional[str] = None,
    ) -> List[Any]:
        out: List[Any] = []
        for meta in self._tools.values():
            if not include_high_risk and meta.get("high_risk"):
                continue
            if domain is not None and meta.get("domain") != domain:
                continue
            out.append(meta["tool"])
        return out

    def get_metadata(self, name: str) -> Optional[Dict[str, Any]]:
        return self._tools.get(name)


TOOL_REGISTRY = ToolRegistry()


def register_tool(
    tool: Any,
    *,
    name: Optional[str] = None,
    read_only: bool = True,
    high_risk: bool = False,
    domain: str = "generic",
) -> Any:
    """
    注册工具到全局 TOOL_REGISTRY。

    既可在模块初始化时直接调用，也可用作简单装饰器：

        @register_tool(read_only=True, domain="pipeline")
        def my_tool(...):
            ...
    """

    if callable(tool) and name is None and not isinstance(tool, str):
        # 兼容作为装饰器使用的情况
        TOOL_REGISTRY.register(tool, name=name, read_only=read_only, high_risk=high_risk, domain=domain)
        return tool

    TOOL_REGISTRY.register(tool, name=name, read_only=read_only, high_risk=high_risk, domain=domain)
    return tool


def list_registered_tools() -> List[Any]:
    """返回注册表中所有工具实例。"""

    return TOOL_REGISTRY.list_tools()


