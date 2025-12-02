from __future__ import annotations

import asyncio
from typing import Any, Dict

import pytest

from cv_agent.server import api


class _DummyTool:
    def __init__(self, result: Dict[str, Any]) -> None:
        self.result = result
        self.called_with: Dict[str, Any] | None = None

    async def ainvoke(self, args: Dict[str, Any]) -> Dict[str, Any]:  # type: ignore[override]
        self.called_with = dict(args)
        return self.result


@pytest.mark.asyncio
async def test_control_plan_delete_uses_plan_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    """plan 模式下 pipeline.delete 仅调用 plan 工具且返回成功计划。"""

    dummy_plan = _DummyTool({"pipeline_name": "demo", "found": True, "plan": {"action": "delete"}})
    monkeypatch.setattr(api, "plan_delete_pipeline_tool", dummy_plan)

    user = api.UserContext(user_id="u1", role="viewer", tenant="tenant-a")
    control = api.ControlRequest(
        op="pipeline.delete",
        mode="plan",
        params=api.ControlParams(pipeline_name="demo"),
        confirm=False,
    )

    msg, result = await api._handle_control(control, user)  # type: ignore[attr-defined]

    assert result.success is True
    assert result.plan == dummy_plan.result
    assert result.result is None
    assert result.execute_result is None
    assert result.plan_steps and result.plan_steps[0]["pipeline_name"] == "demo"
    assert "计划删除 pipeline" in msg.content
    assert dummy_plan.called_with is not None
    assert dummy_plan.called_with["pipeline_name"] == "demo"
    assert dummy_plan.called_with["tenant"] == "tenant-a"


@pytest.mark.asyncio
async def test_control_execute_without_confirm_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    """execute 模式但 confirm=false 时，pipeline.delete 应被拒绝执行。"""

    dummy_plan = _DummyTool({"pipeline_name": "demo", "found": True, "plan": {"action": "delete"}})
    monkeypatch.setattr(api, "plan_delete_pipeline_tool", dummy_plan)

    user = api.UserContext(user_id="u2", role="admin", tenant="tenant-b")
    control = api.ControlRequest(
        op="pipeline.delete",
        mode="execute",
        params=api.ControlParams(pipeline_name="demo"),
        confirm=False,
    )

    msg, result = await api._handle_control(control, user)  # type: ignore[attr-defined]

    assert result.success is False
    assert "必须设置 confirm=true" in (result.error or "")
    # 仍应返回 plan 信息，便于前端展示计划
    assert result.plan is not None
    assert result.plan.get("pipeline_name") == "demo"
    assert "计划删除 pipeline" in msg.content or "控制操作失败" in msg.content


@pytest.mark.asyncio
async def test_control_execute_permission_denied_for_viewer(monkeypatch: pytest.MonkeyPatch) -> None:
    """viewer 角色在 execute 模式下应被权限检查阻止高危控制操作。"""

    dummy_plan = _DummyTool({"pipeline_name": "demo", "found": True, "plan": {"action": "delete"}})
    monkeypatch.setattr(api, "plan_delete_pipeline_tool", dummy_plan)

    user = api.UserContext(user_id="u3", role="viewer", tenant="tenant-c")
    control = api.ControlRequest(
        op="pipeline.delete",
        mode="execute",
        params=api.ControlParams(pipeline_name="demo"),
        confirm=True,
    )

    msg, result = await api._handle_control(control, user)  # type: ignore[attr-defined]

    assert result.success is False
    assert "无权执行" in (result.error or "")
    assert "role=viewer" in (result.error or "")
    # 没有进入真正的执行阶段
    assert result.execute_result is None
    assert "控制操作失败" in msg.content

