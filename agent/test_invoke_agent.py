"""
Minimal E2E invocation helper for the CV agent service.

用法示例（在主机上，docker compose 已经启动 agent 后）::

    python -m venv .venv
    source .venv/bin/activate
    pip install httpx
    python agent/test_invoke_agent.py
"""

from __future__ import annotations

import json
from typing import Any, Dict, List

import httpx


def build_request_payload(question: str) -> Dict[str, Any]:
    messages: List[Dict[str, str]] = [
        {"role": "user", "content": question},
    ]
    return {"messages": messages}


def main() -> None:
    url = "http://localhost:18081/v1/agent/invoke"
    payload = build_request_payload("列出当前所有 pipeline。")

    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
        data = response.json()

    print("=== /v1/agent/invoke response ===")
    print(json.dumps(data, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


