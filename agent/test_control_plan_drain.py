"""
最小 control 协议集成测试：pipeline.drain（plan 模式）。

前置条件：
  - docker compose 已启动 agent（端口 18081）；
  - ControlPlane 正常运行；
  - 可选：环境变量 AGENT_TEST_PIPELINE_NAME 指定一个存在的 pipeline。
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

import httpx


def build_payload(pipeline_name: str, timeout_sec: Optional[int]) -> Dict[str, Any]:
    return {
        "messages": [
            {
                "role": "user",
                "content": (
                    f"计划对 pipeline '{pipeline_name}' 执行 drain，"
                    f"timeout_sec={timeout_sec if timeout_sec is not None else '默认'}。"
                ),
            }
        ],
        "control": {
            "op": "pipeline.drain",
            "mode": "plan",
            "params": {
                "pipeline_name": pipeline_name,
                "node": None,
                "model_uri": None,
                "timeout_sec": timeout_sec,
            },
            "confirm": False,
        },
    }


def main() -> None:
    url = os.environ.get(
        "AGENT_TEST_ENDPOINT", "http://localhost:18081/v1/agent/threads/test-drain/invoke"
    )
    pipeline_name = os.environ.get("AGENT_TEST_PIPELINE_NAME", "demo-pipeline")
    timeout_env = os.environ.get("AGENT_TEST_DRAIN_TIMEOUT")
    timeout_sec = int(timeout_env) if timeout_env is not None else None

    payload = build_payload(pipeline_name, timeout_sec)

    with httpx.Client(timeout=10.0) as client:
        resp = client.post(url, json=payload)
        resp.raise_for_status()
        data = resp.json()

    print("=== control_result ===")
    print(json.dumps(data.get("control_result"), ensure_ascii=False, indent=2))
    print("\n=== message ===")
    print(json.dumps(data.get("message"), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

